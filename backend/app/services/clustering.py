"""Clustering service for grouping similar images."""
import logging
import uuid
from collections import Counter
from typing import Literal

import hdbscan
import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors

from app.core.config import get_settings
from app.models import ClusteringMethod

logger = logging.getLogger(__name__)
settings = get_settings()


class ClusteringResult:
    """Result from clustering operation."""

    def __init__(
        self,
        labels: np.ndarray,
        centroids: np.ndarray | None,
        outlier_scores: np.ndarray | None,
        method: ClusteringMethod,
        run_id: str,
        n_clusters: int,
    ):
        self.labels = labels  # Cluster label for each image (-1 for noise in HDBSCAN)
        self.centroids = centroids  # Centroid for each cluster
        self.outlier_scores = outlier_scores  # Outlier/noise score for each image
        self.method = method
        self.run_id = run_id
        self.n_clusters = n_clusters


class ClusteringService:
    """Service for clustering images based on embeddings."""

    def __init__(self):
        self.method = ClusteringMethod(settings.clustering_method)
        self.min_cluster_size = settings.hdbscan_min_cluster_size
        self.min_samples = settings.hdbscan_min_samples
        self.max_clusters = settings.kmeans_max_clusters

    def cluster(
        self,
        embeddings: np.ndarray,
        method: ClusteringMethod | None = None,
    ) -> ClusteringResult:
        """
        Cluster embeddings into groups.

        Args:
            embeddings: 2D array of shape (n_samples, n_features)
            method: Clustering method to use (defaults to settings)

        Returns:
            ClusteringResult with cluster assignments and metadata
        """
        method = method or self.method
        run_id = uuid.uuid4().hex[:16]

        if len(embeddings) < 2:
            # Not enough data to cluster
            return ClusteringResult(
                labels=np.array([0] * len(embeddings)),
                centroids=np.mean(embeddings, axis=0, keepdims=True) if len(embeddings) > 0 else None,
                outlier_scores=np.zeros(len(embeddings)),
                method=method,
                run_id=run_id,
                n_clusters=1 if len(embeddings) > 0 else 0,
            )

        logger.info(f"Clustering {len(embeddings)} embeddings using {method.value}")

        if method == ClusteringMethod.HDBSCAN:
            return self._cluster_hdbscan(embeddings, run_id)
        elif method == ClusteringMethod.KMEANS:
            return self._cluster_kmeans(embeddings, run_id)
        elif method == ClusteringMethod.GRAPH:
            return self._cluster_graph(embeddings, run_id)
        else:
            raise ValueError(f"Unknown clustering method: {method}")

    def _cluster_hdbscan(self, embeddings: np.ndarray, run_id: str) -> ClusteringResult:
        """Cluster using HDBSCAN."""
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=max(2, self.min_cluster_size),
            min_samples=max(1, self.min_samples),
            metric="euclidean",
            cluster_selection_method="eom",
        )

        labels = clusterer.fit_predict(embeddings)
        outlier_scores = clusterer.outlier_scores_ if hasattr(clusterer, "outlier_scores_") else None

        # Compute centroids for each cluster
        unique_labels = set(labels) - {-1}
        n_clusters = len(unique_labels)
        centroids = np.zeros((n_clusters, embeddings.shape[1]))

        label_to_idx = {label: idx for idx, label in enumerate(sorted(unique_labels))}
        for label in unique_labels:
            mask = labels == label
            centroids[label_to_idx[label]] = embeddings[mask].mean(axis=0)

        logger.info(f"HDBSCAN found {n_clusters} clusters, {(labels == -1).sum()} noise points")

        return ClusteringResult(
            labels=labels,
            centroids=centroids,
            outlier_scores=outlier_scores,
            method=ClusteringMethod.HDBSCAN,
            run_id=run_id,
            n_clusters=n_clusters,
        )

    def _cluster_kmeans(self, embeddings: np.ndarray, run_id: str) -> ClusteringResult:
        """Cluster using K-means with automatic K selection."""
        # Find optimal K using silhouette score
        max_k = min(self.max_clusters, len(embeddings) - 1, 20)
        min_k = 2

        if max_k < min_k:
            # Not enough data for proper clustering
            return ClusteringResult(
                labels=np.zeros(len(embeddings), dtype=int),
                centroids=np.mean(embeddings, axis=0, keepdims=True),
                outlier_scores=None,
                method=ClusteringMethod.KMEANS,
                run_id=run_id,
                n_clusters=1,
            )

        best_k = min_k
        best_score = -1

        for k in range(min_k, max_k + 1):
            kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
            labels = kmeans.fit_predict(embeddings)
            score = silhouette_score(embeddings, labels)

            if score > best_score:
                best_score = score
                best_k = k

        logger.info(f"K-means selected K={best_k} (silhouette={best_score:.3f})")

        # Fit final model
        kmeans = KMeans(n_clusters=best_k, random_state=42, n_init=10)
        labels = kmeans.fit_predict(embeddings)

        # Compute distances to centroids for outlier detection
        distances = np.linalg.norm(
            embeddings - kmeans.cluster_centers_[labels], axis=1
        )
        # Normalize distances to 0-1 scale
        outlier_scores = (distances - distances.min()) / (distances.max() - distances.min() + 1e-8)

        return ClusteringResult(
            labels=labels,
            centroids=kmeans.cluster_centers_,
            outlier_scores=outlier_scores,
            method=ClusteringMethod.KMEANS,
            run_id=run_id,
            n_clusters=best_k,
        )

    def _cluster_graph(self, embeddings: np.ndarray, run_id: str) -> ClusteringResult:
        """Cluster using kNN graph with Louvain community detection."""
        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities
        except ImportError:
            logger.warning("NetworkX not installed, falling back to HDBSCAN")
            return self._cluster_hdbscan(embeddings, run_id)

        # Build kNN graph
        k = min(10, len(embeddings) - 1)
        nn = NearestNeighbors(n_neighbors=k + 1, metric="cosine")
        nn.fit(embeddings)
        distances, indices = nn.kneighbors(embeddings)

        # Create graph
        G = nx.Graph()
        G.add_nodes_from(range(len(embeddings)))

        for i in range(len(embeddings)):
            for j, dist in zip(indices[i][1:], distances[i][1:]):
                weight = 1 - dist  # Convert distance to similarity
                if weight > 0.5:  # Only connect similar nodes
                    G.add_edge(i, j, weight=weight)

        # Find communities using Louvain
        communities = louvain_communities(G, resolution=1.0)

        # Convert to labels
        labels = np.full(len(embeddings), -1)
        for cluster_id, community in enumerate(communities):
            for node in community:
                labels[node] = cluster_id

        n_clusters = len(communities)

        # Compute centroids
        centroids = np.zeros((n_clusters, embeddings.shape[1]))
        for i in range(n_clusters):
            mask = labels == i
            if mask.any():
                centroids[i] = embeddings[mask].mean(axis=0)

        logger.info(f"Graph clustering found {n_clusters} communities")

        return ClusteringResult(
            labels=labels,
            centroids=centroids,
            outlier_scores=None,
            method=ClusteringMethod.GRAPH,
            run_id=run_id,
            n_clusters=n_clusters,
        )

    def find_representative_images(
        self,
        embeddings: np.ndarray,
        labels: np.ndarray,
        centroid: np.ndarray,
        cluster_label: int,
        n_representatives: int = 6,
    ) -> list[int]:
        """Find images closest to cluster centroid."""
        mask = labels == cluster_label
        indices = np.where(mask)[0]

        if len(indices) == 0:
            return []

        cluster_embeddings = embeddings[mask]
        distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
        sorted_idx = np.argsort(distances)

        return [int(indices[i]) for i in sorted_idx[:n_representatives]]

    def compute_common_tags(
        self,
        all_tags: list[list[str]],
        top_n: int = 10,
    ) -> list[str]:
        """Compute most common tags across a set of images."""
        counter = Counter()
        for tags in all_tags:
            counter.update(tags)
        return [tag for tag, _ in counter.most_common(top_n)]


# Singleton instance
_clustering_service: ClusteringService | None = None


def get_clustering_service() -> ClusteringService:
    """Get clustering service singleton."""
    global _clustering_service
    if _clustering_service is None:
        _clustering_service = ClusteringService()
    return _clustering_service
