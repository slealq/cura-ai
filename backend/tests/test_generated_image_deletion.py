"""Hermetic tests for generated-image deletion."""
from unittest.mock import AsyncMock, Mock, call

import pytest

from app.services.generation_service import GenerationService


def _service(db, storage, user_id=7):
    service = GenerationService.__new__(GenerationService)
    service.db = db
    service.user_id = user_id
    service.storage = storage
    return service


@pytest.mark.asyncio
async def test_delete_generated_image_removes_storage_and_database_row():
    events = []
    generated_image = Mock(
        id=12,
        object_key="result.png",
        thumbnail_uri_small="azure://generated_thumbnails/result_200.jpg",
        thumbnail_uri_medium="/storage/generated_thumbnails/result_400.jpg",
    )
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = generated_image
    db = Mock()
    db.query.return_value = query
    db.delete.side_effect = lambda row: events.append(("db_delete", row))
    storage = Mock()

    async def delete_files(*args, **kwargs):
        events.append(("storage_delete", args, kwargs))
        return {"deleted": 3, "failed": 0}

    storage.delete_image_files = AsyncMock(side_effect=delete_files)
    service = _service(db, storage)

    assert await service.delete_generated_image(12) is True

    storage.delete_image_files.assert_awaited_once_with(
        "result.png",
        [
            "azure://generated_thumbnails/result_200.jpg",
            "/storage/generated_thumbnails/result_400.jpg",
        ],
        original_subdir="generated",
        thumbnail_subdir="generated_thumbnails",
    )
    assert events[0][0] == "storage_delete"
    assert events[1] == ("db_delete", generated_image)
    db.commit.assert_called_once_with()


@pytest.mark.asyncio
async def test_bulk_delete_generated_images_only_processes_owned_ids():
    owned_query = Mock()
    owned_query.filter.return_value = owned_query
    owned_query.all.return_value = [(11,), (13,)]
    db = Mock()
    db.query.return_value = owned_query
    service = _service(db, Mock(), user_id=7)
    service.delete_generated_image = AsyncMock(return_value=True)

    deleted = await service.bulk_delete_generated_images([11, 12, 13])

    assert deleted == 2
    assert service.delete_generated_image.await_args_list == [call(11), call(13)]

