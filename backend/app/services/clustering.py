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

from app.models import ClusteringMethod
from app.services.settings_service import DEFAULT_CLUSTERING_CONFIG

logger = logging.getLogger(__name__)


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

    def cluster(
        self,
        embeddings: np.ndarray,
        params: dict | None = None,
    ) -> ClusteringResult:
        """
        Cluster embeddings into groups.

        Args:
            embeddings: 2D array of shape (n_samples, n_features)
            params: Clustering config dict (from settings). Uses defaults if None.

        Returns:
            ClusteringResult with cluster assignments and metadata
        """
        if params is None:
            params = dict(DEFAULT_CLUSTERING_CONFIG)

        method = ClusteringMethod(params.get("method", "hdbscan"))
        run_id = uuid.uuid4().hex[:16]

        if len(embeddings) < 2:
            return ClusteringResult(
                labels=np.array([0] * len(embeddings)),
                centroids=np.mean(embeddings, axis=0, keepdims=True) if len(embeddings) > 0 else None,
                outlier_scores=np.zeros(len(embeddings)),
                method=method,
                run_id=run_id,
                n_clusters=1 if len(embeddings) > 0 else 0,
            )

        logger.info(f"Clustering {len(embeddings)} embeddings using {method.value}")

        # Optionally reduce dimensionality with UMAP before clustering
        original_embeddings = embeddings
        if params.get("use_umap", False) and embeddings.shape[1] > params.get("umap_n_components", 15):
            embeddings = self._reduce_umap(embeddings, params)

        if method == ClusteringMethod.HDBSCAN:
            result = self._cluster_hdbscan(embeddings, original_embeddings, params, run_id)
        elif method == ClusteringMethod.KMEANS:
            result = self._cluster_kmeans(embeddings, original_embeddings, params, run_id)
        elif method == ClusteringMethod.GRAPH:
            result = self._cluster_graph(embeddings, original_embeddings, run_id)
        else:
            raise ValueError(f"Unknown clustering method: {method}")

        return result

    def _reduce_umap(self, embeddings: np.ndarray, params: dict) -> np.ndarray:
        """Reduce embedding dimensionality using UMAP."""
        import umap

        n_components = params.get("umap_n_components", 15)
        n_neighbors = params.get("umap_n_neighbors", 15)
        min_dist = params.get("umap_min_dist", 0.0)
        metric = params.get("umap_metric", "cosine")

        logger.info(
            f"UMAP reducing {embeddings.shape[1]} → {n_components} dims "
            f"(n_neighbors={n_neighbors}, min_dist={min_dist}, metric={metric})"
        )

        reducer = umap.UMAP(
            n_components=n_components,
            n_neighbors=n_neighbors,
            min_dist=min_dist,
            metric=metric,
            random_state=42,
        )
        reduced = reducer.fit_transform(embeddings)
        logger.info(f"UMAP reduction complete: {embeddings.shape} → {reduced.shape}")
        return reduced

    def _compute_centroids_original_space(
        self,
        labels: np.ndarray,
        original_embeddings: np.ndarray,
    ) -> tuple[np.ndarray, int]:
        """Compute centroids in original embedding space (for pgvector storage)."""
        unique_labels = set(labels) - {-1}
        n_clusters = len(unique_labels)
        centroids = np.zeros((n_clusters, original_embeddings.shape[1]))

        label_to_idx = {label: idx for idx, label in enumerate(sorted(unique_labels))}
        for label in unique_labels:
            mask = labels == label
            centroids[label_to_idx[label]] = original_embeddings[mask].mean(axis=0)

        return centroids, n_clusters

    def _cluster_hdbscan(
        self,
        embeddings: np.ndarray,
        original_embeddings: np.ndarray,
        params: dict,
        run_id: str,
    ) -> ClusteringResult:
        """Cluster using HDBSCAN."""
        min_cluster_size = max(2, params.get("hdbscan_min_cluster_size", 15))
        min_samples = max(1, params.get("hdbscan_min_samples", 5))
        cluster_selection_method = params.get("hdbscan_cluster_selection_method", "eom")

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            metric="euclidean",
            cluster_selection_method=cluster_selection_method,
        )

        labels = clusterer.fit_predict(embeddings)
        outlier_scores = clusterer.outlier_scores_ if hasattr(clusterer, "outlier_scores_") else None

        # Compute centroids in original space for pgvector
        centroids, n_clusters = self._compute_centroids_original_space(labels, original_embeddings)

        logger.info(f"HDBSCAN found {n_clusters} clusters, {(labels == -1).sum()} noise points")

        return ClusteringResult(
            labels=labels,
            centroids=centroids,
            outlier_scores=outlier_scores,
            method=ClusteringMethod.HDBSCAN,
            run_id=run_id,
            n_clusters=n_clusters,
        )

    def _cluster_kmeans(
        self,
        embeddings: np.ndarray,
        original_embeddings: np.ndarray,
        params: dict,
        run_id: str,
    ) -> ClusteringResult:
        """Cluster using K-means with automatic K selection."""
        max_clusters = params.get("kmeans_max_clusters", 50)
        max_k = min(max_clusters, len(embeddings) - 1, 20)
        min_k = 2

        if max_k < min_k:
            return ClusteringResult(
                labels=np.zeros(len(embeddings), dtype=int),
                centroids=np.mean(original_embeddings, axis=0, keepdims=True),
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

        # Compute centroids in original space for pgvector
        centroids, n_clusters = self._compute_centroids_original_space(labels, original_embeddings)

        # Compute distances for outlier scoring (in clustering space)
        distances = np.linalg.norm(
            embeddings - kmeans.cluster_centers_[labels], axis=1
        )
        outlier_scores = (distances - distances.min()) / (distances.max() - distances.min() + 1e-8)

        return ClusteringResult(
            labels=labels,
            centroids=centroids,
            outlier_scores=outlier_scores,
            method=ClusteringMethod.KMEANS,
            run_id=run_id,
            n_clusters=n_clusters,
        )

    def _cluster_graph(
        self,
        embeddings: np.ndarray,
        original_embeddings: np.ndarray,
        run_id: str,
    ) -> ClusteringResult:
        """Cluster using kNN graph with Louvain community detection."""
        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities
        except ImportError:
            logger.warning("NetworkX not installed, falling back to HDBSCAN")
            return self._cluster_hdbscan(
                embeddings, original_embeddings, dict(DEFAULT_CLUSTERING_CONFIG), run_id
            )

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
                weight = 1 - dist
                if weight > 0.5:
                    G.add_edge(i, j, weight=weight)

        # Find communities using Louvain
        communities = louvain_communities(G, resolution=1.0)

        # Convert to labels
        labels = np.full(len(embeddings), -1)
        for cluster_id, community in enumerate(communities):
            for node in community:
                labels[node] = cluster_id

        n_clusters = len(communities)

        # Compute centroids in original space for pgvector
        centroids = np.zeros((n_clusters, original_embeddings.shape[1]))
        for i in range(n_clusters):
            mask = labels == i
            if mask.any():
                centroids[i] = original_embeddings[mask].mean(axis=0)

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


def get_clustering_service() -> ClusteringService:
    """Get clustering service instance."""
    return ClusteringService()
