"""Hermetic tests for periodic empty-cluster cleanup."""
from unittest.mock import Mock

from app.services import storage as storage_module
from app.workers import tasks as tasks_module


def test_cleanup_empty_clusters_deletes_only_query_results(monkeypatch):
    empty_with_cover = Mock(id=21, user_id=4, cover_thumbnail_uri="cluster_21.jpg")
    empty_without_cover = Mock(id=22, user_id=5, cover_thumbnail_uri=None)
    query = Mock()
    query.filter.return_value = query
    query.all.return_value = [empty_with_cover, empty_without_cover]
    db = Mock()
    db.query.return_value = query
    storage = Mock()

    monkeypatch.setattr(tasks_module, "SessionLocal", Mock(return_value=db))
    monkeypatch.setattr(
        storage_module, "get_storage_service", Mock(return_value=storage)
    )

    tasks_module.cleanup_empty_clusters.run()

    query.filter.assert_called_once()
    filter_expression = str(query.filter.call_args.args[0])
    assert "clusters.id NOT IN" in filter_expression
    assert "cluster_memberships.cluster_id" in filter_expression
    storage.delete_cluster_cover_sync.assert_called_once_with(21)
    assert db.delete.call_args_list[0].args == (empty_with_cover,)
    assert db.delete.call_args_list[1].args == (empty_without_cover,)
    assert db.commit.call_count == 2
    db.rollback.assert_not_called()
    db.close.assert_called_once_with()


def test_cleanup_empty_clusters_rolls_back_on_failure(monkeypatch):
    db = Mock()
    db.query.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(tasks_module, "SessionLocal", Mock(return_value=db))

    tasks_module.cleanup_empty_clusters.run()

    db.rollback.assert_called_once_with()
    db.close.assert_called_once_with()
