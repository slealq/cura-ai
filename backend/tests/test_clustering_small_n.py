"""Tier-1 hermetic regressions using real clustering algorithms, without DB or network."""

import numpy as np
import pytest

# CI installs umap-learn; allow lightweight environments without it to skip cleanly.
pytest.importorskip("umap")

from app.models import ClusteringMethod
from app.services.clustering import ClusteringResult, ClusteringService
from app.services.settings_service import DEFAULT_CLUSTERING_CONFIG


@pytest.mark.parametrize("n_samples", [2, 3, 4, 5, 10, 14, 15, 16, 17, 18])
@pytest.mark.parametrize("method", ["hdbscan", "kmeans", "graph"])
def test_small_sample_clustering_with_default_umap(n_samples, method):
    """Default 15-component UMAP previously failed spectral init, e.g. at N=5."""
    embeddings = np.random.default_rng(42).normal(size=(n_samples, 64)).astype(np.float32)
    params = {**DEFAULT_CLUSTERING_CONFIG, "method": method, "use_umap": True}

    result = ClusteringService().cluster(embeddings, params)

    assert isinstance(result, ClusteringResult)
    assert result.method is ClusteringMethod(method)
    assert result.labels.shape == (n_samples,)
    assert 0 <= result.n_clusters <= n_samples
    assert result.n_clusters == len(set(result.labels) - {-1})
    assert result.centroids.shape == (result.n_clusters, embeddings.shape[1])
    assert np.isfinite(result.centroids).all()


@pytest.mark.parametrize("n_samples", [2, 3])
def test_reduce_umap_directly_skips_too_few_samples(n_samples, caplog):
    embeddings = np.ones((n_samples, 64), dtype=np.float32)

    with caplog.at_level("INFO", logger="app.services.clustering"):
        reduced = ClusteringService()._reduce_umap(embeddings, DEFAULT_CLUSTERING_CONFIG)

    assert reduced is embeddings
    assert "Skipping UMAP" in caplog.text


def test_reduce_umap_clamps_small_sample_parameters(caplog):
    embeddings = np.random.default_rng(42).normal(size=(5, 64)).astype(np.float32)

    with caplog.at_level("INFO", logger="app.services.clustering"):
        reduced = ClusteringService()._reduce_umap(embeddings, DEFAULT_CLUSTERING_CONFIG)

    assert reduced.shape == (5, 3)
    assert np.isfinite(reduced).all()
    assert "Clamping UMAP" in caplog.text


def test_reduce_umap_skips_when_features_cannot_be_reduced():
    embeddings = np.ones((5, 2), dtype=np.float32)

    assert ClusteringService()._reduce_umap(embeddings, DEFAULT_CLUSTERING_CONFIG) is embeddings
