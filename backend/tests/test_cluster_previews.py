"""Contact strip previews use bounded, tenant-scoped bulk queries without storage I/O."""
from types import SimpleNamespace
from unittest.mock import Mock

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from app.services import cluster_service as module
from app.services.cluster_service import ClusterService


def test_previews_prioritize_active_representatives_and_fill_in_two_queries(monkeypatch):
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE images (id INTEGER PRIMARY KEY, user_id INTEGER, width INTEGER, height INTEGER, thumbnail_uri_medium TEXT, thumbnail_uri_small TEXT)'))
        conn.execute(text('CREATE TABLE cluster_memberships (cluster_id INTEGER, image_id INTEGER, is_excluded BOOLEAN)'))
        for image_id in range(1, 24):
            conn.execute(text('INSERT INTO images VALUES (:id, :user, 600, 900, :uri, NULL)'),
                         dict(id=image_id, user=9 if image_id == 23 else 4, uri=f'preview-{image_id}.jpg'))
            conn.execute(text('INSERT INTO cluster_memberships VALUES (:cluster, :id, :excluded)'),
                         dict(cluster=11 if image_id < 13 else 12, id=image_id, excluded=image_id == 11))
    statements = []
    event.listen(engine, 'before_cursor_execute', lambda conn, cursor, statement, params, context, many: statements.append(statement))
    storage = Mock()
    storage.generate_thumbnail_sas_url.side_effect = lambda uri: f'signed:{uri}'
    monkeypatch.setattr(module, 'get_storage_service', lambda: storage)
    service = ClusterService.__new__(ClusterService)
    service.user_id = 4
    with Session(engine) as db:
        service.db = db
        result = service.get_preview_images([
            SimpleNamespace(id=11, representative_image_ids=[12, 11, 10, 12, 999]),
            SimpleNamespace(id=12, representative_image_ids=[23, 22]),
        ])
    assert len(statements) == 2
    assert [i['id'] for i in result[11]] == [12, 10, 1, 2, 3, 4, 5, 6]
    assert [i['id'] for i in result[12]] == [22, 13, 14, 15, 16, 17, 18, 19]
    assert all(i['width'] == 600 and i['height'] == 900 for images in result.values() for i in images)
    assert result[11][0]['thumbnail_url'] == 'signed:preview-12.jpg'
    assert storage.generate_thumbnail_sas_url.call_count == 16
    assert 'row_number() OVER' in statements[1]
    assert 'rank <= ?' in statements[1]


def test_no_clusters_needs_no_queries():
    service = ClusterService.__new__(ClusterService)
    service.db = Mock()
    assert service.get_preview_images([]) == {}
    service.db.query.assert_not_called()


def test_cluster_list_pages_after_filtering_and_sorts_pins_first(monkeypatch):
    import asyncio
    from datetime import datetime

    from app.api import clusters as api
    from app.models import Cluster, ClusteringMethod

    def cluster(id, size, title, pinned=False, archived=False):
        return Cluster(id=id, user_id=4, run_id="test", size=size,
                       method=ClusteringMethod.KMEANS, summary_title=title,
                       summary_description="- First sentence.", common_tags=["landscape"],
                       representative_image_ids=[], display_name=None, is_pinned=pinned,
                       is_archived=archived, created_at=datetime(2026, 10, 31),
                       updated_at=datetime(2026, 10, 31))

    service = Mock()
    service.get_latest_clusters.return_value = [
        cluster(1, 100, "Zebra"), cluster(2, 3, "Pinned", pinned=True),
        cluster(3, 20, "Apple"), cluster(4, 9, "Unclustered Images"),
        cluster(5, 200, "Archived", archived=True),
    ]
    service.get_preview_images.return_value = {}
    monkeypatch.setattr(api, 'get_cluster_service', lambda db, user_id: service)
    monkeypatch.setattr(api, 'get_storage_service', lambda: Mock(generate_cluster_cover_sas_url=lambda uri: None))
    result = asyncio.run(api.list_clusters(
        include_archived=False, search="", sort="name", skip=1, limit=1,
        db=Mock(), current_user=SimpleNamespace(id=4),
    ))
    assert result.total == 4
    assert [c.id for c in result.items] == [3]
    assert result.overview.clusters == 3
    assert result.overview.grouped == 123
    assert result.overview.unclustered.id == 4
    assert [c.id for c in result.overview.largest] == [1, 3, 2]
    service.get_preview_images.assert_called_once()
    assert [c.id for c in service.get_preview_images.call_args.args[0]] == [3]

    result = asyncio.run(api.list_clusters(
        include_archived=False, search="landscape", sort="size", skip=0, limit=2,
        db=Mock(), current_user=SimpleNamespace(id=4),
    ))
    assert [c.id for c in result.items] == [2, 1]
    result = asyncio.run(api.list_clusters(
        include_archived=False, search="apple", sort="size", skip=0, limit=20,
        db=Mock(), current_user=SimpleNamespace(id=4),
    ))
    assert result.total == 1
    assert result.items[0].id == 3


def test_merge_initializes_tags_as_a_list():
    first = SimpleNamespace(id=11, method='kmeans', run_id='run', centroid_embedding=None,
                            representative_image_ids=[1], is_archived=False)
    second = SimpleNamespace(id=12, representative_image_ids=[2], is_archived=False)
    cluster_query = Mock()
    cluster_query.filter.return_value.all.return_value = [first, second]
    memberships = Mock()
    memberships.filter.return_value.all.return_value = [SimpleNamespace(image_id=1)]
    db = Mock()
    db.query.side_effect = [cluster_query, memberships, memberships, Mock(), Mock()]
    db.flush.side_effect = lambda: setattr(db.add.call_args.args[0], 'id', 20)
    service = ClusterService.__new__(ClusterService)
    service.db = db
    service.user_id = 4
    merged = service.merge_clusters([11, 12])
    assert merged.common_tags == []
    assert merged.size == 1
    assert first.is_archived and second.is_archived


def test_merge_queues_summary(monkeypatch):
    import asyncio

    from app.api import clusters as api
    from app.schemas import ClusterMergeRequest, ClusterResponse

    service = Mock()
    service.merge_clusters.return_value = ClusterResponse.model_construct(id=20)
    monkeypatch.setattr(api, 'get_cluster_service', lambda db, user_id: service)
    dispatch = Mock()
    monkeypatch.setattr(api, 'dispatch', dispatch)
    result = asyncio.run(api.merge_clusters(
        ClusterMergeRequest(cluster_ids=[11, 12]), Mock(), SimpleNamespace(id=4),
    ))
    assert result.id == 20
    dispatch.assert_called_once_with(api.summarize_cluster, 20, 4)
