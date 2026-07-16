"""Cluster service for managing image clusters."""
import logging
from io import BytesIO

import numpy as np
from PIL import Image as PILImage
from sqlalchemy import String, cast
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Cluster,
    ClusteringMethod,
    ClusterMembership,
    Image,
)
from app.services.clustering import ClusteringResult, get_clustering_service
from app.services.cover_utils import generate_cover_composite, sample_candidates
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


class ClusterService:
    """Service for cluster CRUD and management operations."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.clustering_service = get_clustering_service()

    def get_cluster(self, cluster_id: int) -> Cluster | None:
        """Get cluster by ID with memberships."""
        return (
            self.db.query(Cluster)
            .options(joinedload(Cluster.memberships))
            .filter(Cluster.id == cluster_id, Cluster.user_id == self.user_id)
            .first()
        )

    def get_clusters(
        self,
        run_id: str | None = None,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Cluster]:
        """Get paginated list of clusters."""
        query = (
            self.db.query(Cluster)
            .options(joinedload(Cluster.cover_image))
        )
        query = self._apply_cluster_filters(query, run_id, include_archived)

        try:
            return self._ordered_cluster_query(query, skip, limit).all()
        except LookupError:
            # SQLAlchemy deserializes Enum values while executing .all(), so one
            # malformed row otherwise prevents every valid cluster from loading.
            invalid_cluster_ids = self._find_invalid_cluster_method_ids(run_id, include_archived)
            if not invalid_cluster_ids:
                raise

            return (
                self._ordered_cluster_query(query.filter(Cluster.id.notin_(invalid_cluster_ids)), skip, limit)
                .all()
            )

    def _apply_cluster_filters(self, query, run_id: str | None, include_archived: bool):
        """Apply the user/run/archive filters shared by normal and raw queries."""
        query = query.filter(Cluster.user_id == self.user_id)

        if run_id:
            query = query.filter(Cluster.run_id == run_id)
        if not include_archived:
            query = query.filter(Cluster.is_archived.is_(False))
        return query

    @staticmethod
    def _ordered_cluster_query(query, skip: int, limit: int):
        return (
            query.order_by(Cluster.is_pinned.desc(), Cluster.size.desc())
            .offset(skip)
            .limit(limit)
        )

    def _find_invalid_cluster_method_ids(
        self, run_id: str | None, include_archived: bool
    ) -> list[int]:
        """Return malformed method rows without invoking Enum result coercion."""
        raw_method = cast(Cluster.method, String).label("method")
        raw_query = self.db.query(Cluster.id, raw_method)
        raw_rows = self._apply_cluster_filters(raw_query, run_id, include_archived).all()
        valid_methods = {method.name for method in ClusteringMethod}

        invalid_cluster_ids = []
        for cluster_id, method in raw_rows:
            if method not in valid_methods:
                logger.error("Skipping cluster id=%s with invalid method value=%r", cluster_id, method)
                invalid_cluster_ids.append(cluster_id)

        return invalid_cluster_ids

    def get_latest_clusters(self, limit: int = 100) -> list[Cluster]:
        """Get clusters from the most recent clustering run."""
        # Get the latest run_id
        latest_run = (
            self.db.query(Cluster.run_id)
            .filter(Cluster.user_id == self.user_id)
            .order_by(Cluster.created_at.desc())
            .first()
        )

        if not latest_run:
            return []

        return self.get_clusters(run_id=latest_run[0], limit=limit)

    def get_cluster_images(
        self,
        cluster_id: int,
        include_outliers: bool = True,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Image]:
        """Get images in a cluster."""
        query = (
            self.db.query(Image)
            .join(ClusterMembership)
            .filter(ClusterMembership.cluster_id == cluster_id)
            .filter(ClusterMembership.is_excluded.is_(False))
        )

        if not include_outliers:
            query = query.filter(ClusterMembership.is_outlier.is_(False))

        return (
            query.order_by(ClusterMembership.distance_to_centroid)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def create_clusters_from_result(
        self,
        result: ClusteringResult,
        image_ids: list[int],
        embeddings: np.ndarray,
    ) -> list[Cluster]:
        """Create cluster records from clustering result."""
        clusters = []
        unique_labels = set(result.labels) - {-1}

        # Create a mapping from label to centroid index
        label_to_centroid_idx = {
            label: idx for idx, label in enumerate(sorted(unique_labels))
        }

        for label in sorted(unique_labels):
            mask = result.labels == label
            member_indices = np.where(mask)[0]
            member_image_ids = [image_ids[i] for i in member_indices]

            centroid = result.centroids[label_to_centroid_idx[label]] if result.centroids is not None else None

            # Find representative images
            representative_ids = []
            if centroid is not None:
                rep_indices = self.clustering_service.find_representative_images(
                    embeddings, result.labels, centroid, label, n_representatives=6
                )
                representative_ids = [image_ids[i] for i in rep_indices]

            cluster = Cluster(
                user_id=self.user_id,
                method=result.method,
                run_id=result.run_id,
                centroid_embedding=centroid.tolist() if centroid is not None else None,
                size=len(member_image_ids),
                representative_image_ids=representative_ids,
                cover_image_id=representative_ids[0] if representative_ids else None,
                common_tags=[],
            )

            self.db.add(cluster)
            self.db.flush()  # Get cluster ID

            # Create memberships
            for i, img_id in zip(member_indices, member_image_ids):
                distance = None
                if centroid is not None:
                    distance = float(np.linalg.norm(embeddings[i] - centroid))

                is_outlier = False
                if result.outlier_scores is not None:
                    is_outlier = result.outlier_scores[i] > 0.9

                membership = ClusterMembership(
                    cluster_id=cluster.id,
                    image_id=img_id,
                    distance_to_centroid=distance,
                    is_outlier=is_outlier,
                )
                self.db.add(membership)

            clusters.append(cluster)

        # Handle noise points (label == -1) - create a single "unclustered" group
        noise_mask = result.labels == -1
        if noise_mask.any():
            noise_indices = np.where(noise_mask)[0]
            noise_image_ids = [image_ids[i] for i in noise_indices]

            noise_cluster = Cluster(
                user_id=self.user_id,
                method=result.method,
                run_id=result.run_id,
                centroid_embedding=None,
                size=len(noise_image_ids),
                summary_title="Unclustered Images",
                summary_description="Images that don't fit well into other clusters",
                representative_image_ids=noise_image_ids[:6],
                cover_image_id=noise_image_ids[0] if noise_image_ids else None,
                common_tags=[],
            )

            self.db.add(noise_cluster)
            self.db.flush()

            for i, img_id in zip(noise_indices, noise_image_ids):
                membership = ClusterMembership(
                    cluster_id=noise_cluster.id,
                    image_id=img_id,
                    is_outlier=True,
                )
                self.db.add(membership)

            clusters.append(noise_cluster)

        self.db.commit()
        return clusters

    def update_cluster_summary(
        self,
        cluster_id: int,
        summary_title: str,
        summary_description: str,
        common_tags: list[str],
        summarization_model: str,
    ) -> Cluster | None:
        """Update cluster with AI-generated summary."""
        cluster = self.db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == self.user_id).first()
        if cluster:
            cluster.summary_title = summary_title
            cluster.summary_description = summary_description
            cluster.common_tags = common_tags
            cluster.summarization_model = summarization_model
            self.db.commit()
            self.db.refresh(cluster)
        return cluster

    def rename_cluster(self, cluster_id: int, display_name: str) -> Cluster | None:
        """Set user-defined display name for cluster."""
        cluster = self.db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == self.user_id).first()
        if cluster:
            cluster.display_name = display_name
            self.db.commit()
            self.db.refresh(cluster)
        return cluster

    def toggle_pin(self, cluster_id: int) -> Cluster | None:
        """Toggle pinned status of cluster."""
        cluster = self.db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == self.user_id).first()
        if cluster:
            cluster.is_pinned = not cluster.is_pinned
            self.db.commit()
            self.db.refresh(cluster)
        return cluster

    def archive_cluster(self, cluster_id: int) -> Cluster | None:
        """Archive a cluster."""
        cluster = self.db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == self.user_id).first()
        if cluster:
            cluster.is_archived = True
            self.db.commit()
            self.db.refresh(cluster)
        return cluster

    def merge_clusters(self, cluster_ids: list[int], new_name: str | None = None) -> Cluster:
        """Merge multiple clusters into one."""
        clusters = (
            self.db.query(Cluster)
            .filter(Cluster.id.in_(cluster_ids), Cluster.user_id == self.user_id)
            .all()
        )

        if len(clusters) < 2:
            raise ValueError("Need at least 2 clusters to merge")

        # Use the first cluster's method and run_id
        primary = clusters[0]

        # Create new merged cluster
        all_image_ids = []
        all_representative_ids = []

        for cluster in clusters:
            memberships = (
                self.db.query(ClusterMembership)
                .filter(ClusterMembership.cluster_id == cluster.id)
                .all()
            )
            all_image_ids.extend([m.image_id for m in memberships])
            all_representative_ids.extend(cluster.representative_image_ids[:2])

        rep_ids = list(set(all_representative_ids))[:6]
        merged_cluster = Cluster(
            user_id=self.user_id,
            method=primary.method,
            run_id=primary.run_id,
            centroid_embedding=primary.centroid_embedding,
            size=len(set(all_image_ids)),
            display_name=new_name,
            representative_image_ids=rep_ids,
            cover_image_id=rep_ids[0] if rep_ids else None,
            common_tags={},
        )

        self.db.add(merged_cluster)
        self.db.flush()

        # Move all memberships to new cluster
        for cluster in clusters:
            (
                self.db.query(ClusterMembership)
                .filter(ClusterMembership.cluster_id == cluster.id)
                .update({"cluster_id": merged_cluster.id})
            )
            cluster.is_archived = True

        self.db.commit()
        self.db.refresh(merged_cluster)
        return merged_cluster

    def exclude_image_from_cluster(
        self, cluster_id: int, image_id: int
    ) -> bool:
        """Mark an image as excluded from a cluster."""
        membership = (
            self.db.query(ClusterMembership)
            .filter(
                ClusterMembership.cluster_id == cluster_id,
                ClusterMembership.image_id == image_id,
            )
            .first()
        )

        if membership:
            membership.is_excluded = True

            # Update cluster size
            cluster = self.db.query(Cluster).filter(Cluster.id == cluster_id, Cluster.user_id == self.user_id).first()
            if cluster:
                cluster.size = max(0, cluster.size - 1)

            self.db.commit()
            return True
        return False

    def delete_old_clusters(self, keep_run_id: str | None = None) -> int:
        """Delete old clusters, optionally keeping a specific run."""
        query = self.db.query(Cluster).filter(Cluster.user_id == self.user_id)
        if keep_run_id:
            query = query.filter(Cluster.run_id != keep_run_id)

        # First delete memberships
        cluster_ids = [c.id for c in query.all()]
        (
            self.db.query(ClusterMembership)
            .filter(ClusterMembership.cluster_id.in_(cluster_ids))
            .delete(synchronize_session=False)
        )

        # Then delete clusters
        deleted = query.delete(synchronize_session=False)
        self.db.commit()
        return deleted

    def count_clusters(self, run_id: str | None = None) -> int:
        """Count clusters with optional run_id filter."""
        query = self.db.query(Cluster).filter(Cluster.user_id == self.user_id)
        if run_id:
            query = query.filter(Cluster.run_id == run_id)
        return query.count()

    def generate_cover_composite(self, cluster_id: int) -> None:
        """Generate a justified-row composite JPEG for a cluster cover."""
        cluster = self.get_cluster(cluster_id)
        if not cluster:
            return

        storage = get_storage_service()

        # Fetch up to 20 candidates; include outliers so the "Unclustered" group gets a cover
        candidates = self.get_cluster_images(cluster_id, include_outliers=True, limit=20)
        if not candidates:
            cluster.cover_thumbnail_uri = None
            self.db.commit()
            return

        selected = sample_candidates(candidates)

        # Load PIL images from thumbnails
        pil_images: list[PILImage.Image] = []
        for img in selected:
            uri = img.thumbnail_uri_medium or img.thumbnail_uri_small
            if not uri:
                continue
            data = storage.get_thumbnail_bytes_sync(uri)
            if data:
                try:
                    pil_images.append(PILImage.open(BytesIO(data)).convert("RGB"))
                except Exception:
                    continue

        jpeg_data = generate_cover_composite(pil_images)
        if jpeg_data is None:
            return

        uri = storage.save_cluster_cover_sync(jpeg_data, cluster_id)
        cluster.cover_thumbnail_uri = uri
        self.db.commit()


def get_cluster_service(db: Session, user_id: int) -> ClusterService:
    """Get cluster service instance."""
    return ClusterService(db, user_id)
