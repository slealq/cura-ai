"""Hermetic coverage for recovery from malformed cluster enum values."""
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.models.cluster import Cluster, ClusteringMethod
from app.services.cluster_service import ClusterService


def _query_mock(all_result=None, all_side_effect=None):
    query = Mock()
    query.options.return_value = query
    query.filter.return_value = query
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = all_result
    query.all.side_effect = all_side_effect
    return query


def test_get_clusters_skips_bad_enum_row_after_hydration_failure():
    """A bad row cannot prevent valid clusters from being returned."""
    valid_cluster = Mock(id=18)
    initial_query = _query_mock(all_side_effect=[LookupError("invalid enum value"), [valid_cluster]])
    raw_query = _query_mock(all_result=[(17, "hdbscan"), (18, "HDBSCAN")])
    db = Mock()
    db.query.side_effect = [initial_query, raw_query]

    service = ClusterService.__new__(ClusterService)
    service.db = db
    service.user_id = 42

    with patch("app.services.cluster_service.logger") as logger:
        result = service.get_clusters(run_id="run-1")

    assert result == [valid_cluster]
    logger.error.assert_called_once_with(
        "Skipping cluster id=%s with invalid method value=%r", 17, "hdbscan"
    )
    assert initial_query.all.call_count == 2


def test_cluster_method_enum_binds_and_deserializes_member_names():
    """The database representation is the uppercase enum member name, not its value."""
    enum_type = Cluster.__table__.c.method.type
    dialect = postgresql.dialect()

    assert enum_type.bind_processor(dialect)(ClusteringMethod.HDBSCAN) == "HDBSCAN"
    assert enum_type.result_processor(dialect, None)("HDBSCAN") is ClusteringMethod.HDBSCAN
    assert ClusteringMethod["HDBSCAN"] is ClusteringMethod.HDBSCAN
    with pytest.raises(ValueError):
        ClusteringMethod("HDBSCAN")
