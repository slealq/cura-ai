"""Deletion dispatch and guarded file cleanup with real temporary local files."""
from unittest.mock import MagicMock

import pytest

from app.models import Image
from app.services.image_service import ImageService
from app.services.storage import StorageService
from app.workers import tasks


def image(id=1, user_id=7):
    return Image(id=id, user_id=user_id, object_key=f'{id}.jpg', file_hash='same-hash',
                 thumbnail_uri_small=f'/storage/thumbnails/{id}_200.jpg',
                 thumbnail_uri_medium=f'azure://images/thumbnails/{id}_400.jpg')


@pytest.mark.parametrize('batch', [False, True])
def test_single_and_batch_queue_cleanup_only_after_commit(monkeypatch, batch):
    events = []
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    query.first.return_value = image()
    query.all.return_value = [image()]
    db.commit.side_effect = lambda: events.append('commit')
    cleanup = MagicMock()
    cleanup.delay.side_effect = lambda files: events.append(('cleanup', files))
    monkeypatch.setattr(tasks, 'cleanup_storage_files', cleanup)
    service = ImageService.__new__(ImageService)
    service.db, service.user_id = db, 7
    if batch:
        assert service.delete_images_batch([1, 999]) == 1
    else:
        assert service.delete_image(1)
    assert events[0] == 'commit'
    assert events[1] == ('cleanup', [{'object_key': '1.jpg', 'file_hash': 'same-hash',
                                    'thumbnail_uris': ['/storage/thumbnails/1_200.jpg', 'azure://images/thumbnails/1_400.jpg']}])
    clauses = query.filter.call_args.args
    assert any('images.user_id' in str(clause) and clause.right.value == 7 for clause in clauses)


def test_failed_commit_never_queues_cleanup(monkeypatch):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = image()
    db.commit.side_effect = RuntimeError('commit failed')
    cleanup = MagicMock()
    monkeypatch.setattr(tasks, 'cleanup_storage_files', cleanup)
    service = ImageService.__new__(ImageService)
    service.db, service.user_id = db, 7
    with pytest.raises(RuntimeError):
        service.delete_image(1)
    cleanup.delay.assert_not_called()


def local_storage(tmp_path):
    storage = StorageService.__new__(StorageService)
    storage.storage_backend, storage.local_path = 'local', tmp_path
    for name in ['images/result.jpg', 'thumbnails/shared.jpg', 'thumbnails/unique.jpg', 'history/7-copy.jpg']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'image')
    return storage


def task_db(monkeypatch, storage, answers):
    from app.services import storage as storage_module
    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = answers
    monkeypatch.setattr(tasks, 'SessionLocal', lambda: db)
    monkeypatch.setattr(storage_module, 'get_storage_service', lambda: storage)
    return db


def test_shared_original_and_thumbnail_survive_cleanup(tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    db = task_db(monkeypatch, storage, [(42,), (42,)])
    result = tasks.cleanup_storage_files.run([{'object_key': 'result.jpg', 'file_hash': 'same-hash',
                                               'thumbnail_uris': ['azure://images/thumbnails/shared.jpg']}])
    assert result == {'deleted': 0, 'failed': 0, 'skipped': 2}
    assert (tmp_path / 'images/result.jpg').exists()
    assert (tmp_path / 'thumbnails/shared.jpg').exists()
    assert (tmp_path / 'history/7-copy.jpg').exists()
    # Cleanup is intentionally global: another user can still own the physical file.
    clauses = db.query.return_value.filter.call_args_list[0].args
    assert 'file_hash' in str(clauses[0]) and 'object_key' in str(clauses[0])
    assert 'user_id' not in str(clauses[0])
    db.close.assert_called_once()


def test_unique_files_removed_and_history_never_touched(tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    task_db(monkeypatch, storage, [None, None, None])
    result = tasks.cleanup_storage_files.run([{'object_key': 'result.jpg', 'file_hash': 'unique',
                                               'thumbnail_uris': ['/app/storage/thumbnails/unique.jpg']}])
    assert result == {'deleted': 2, 'failed': 0, 'skipped': 0}
    assert not (tmp_path / 'images/result.jpg').exists()
    assert not (tmp_path / 'thumbnails/unique.jpg').exists()
    assert (tmp_path / 'history/7-copy.jpg').exists()


def test_same_hash_protects_original_with_different_key(tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    task_db(monkeypatch, storage, [(42,)])
    result = tasks.cleanup_storage_files.run([{'object_key': 'result.jpg', 'file_hash': 'shared', 'thumbnail_uris': []}])
    assert result['skipped'] == 1
    assert (tmp_path / 'images/result.jpg').exists()


def test_cleanup_rejects_history_namespace_and_path_escape(tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    task_db(monkeypatch, storage, [])
    result = tasks.cleanup_storage_files.run([{'object_key': '../history/7-copy.jpg'}, {'object_key': 'history/7-copy.jpg'}])
    assert result['skipped'] == 2
    assert (tmp_path / 'history/7-copy.jpg').exists()


def test_unique_original_is_deleted_but_shared_thumbnail_is_kept(tmp_path, monkeypatch):
    storage = local_storage(tmp_path)
    task_db(monkeypatch, storage, [None, (42,)])
    result = tasks.cleanup_storage_files.run([{'object_key': 'result.jpg', 'file_hash': 'unique',
                                               'thumbnail_uris': ['/storage/thumbnails/shared.jpg']}])
    assert result == {'deleted': 1, 'failed': 0, 'skipped': 1}
    assert not (tmp_path / 'images/result.jpg').exists()
    assert (tmp_path / 'thumbnails/shared.jpg').exists()
    assert (tmp_path / 'history/7-copy.jpg').exists()


def test_s3_cleanup_matches_existing_library_writer_keys(monkeypatch):
    import boto3
    client = MagicMock()
    monkeypatch.setattr(boto3, 'client', lambda *args, **kwargs: client)
    storage = StorageService.__new__(StorageService)
    storage.storage_backend = 's3'
    task_db(monkeypatch, storage, [None, None, None])
    result = tasks.cleanup_storage_files.run([{'object_key': 'result.jpg', 'file_hash': 'unique',
                                               'thumbnail_uris': ['s3://bucket/images/thumbnails/unique.jpg']}])
    assert result['deleted'] == 2
    assert [call.kwargs['Key'] for call in client.delete_object.call_args_list] == [
        'images/result.jpg', 'images/thumbnails/unique.jpg']
