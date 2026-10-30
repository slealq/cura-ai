"""Hermetic tests for copying finished generations/edits into the image library."""
from unittest.mock import AsyncMock, Mock

import pytest

import app.services.image_service as image_service_module
import app.workers.tasks as tasks_module
from app.models.image import ImageSource
from app.services.generation_service import GenerationService


def _service(db, user_id=7):
    service = GenerationService.__new__(GenerationService)
    service.db = db
    service.user_id = user_id
    service.storage = Mock()
    return service


def _db(already_linked=False):
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = (99,) if already_linked else None
    db = Mock()
    db.query.return_value = query
    return db


@pytest.fixture
def library(monkeypatch):
    """Patch the upload path and the ingest task; return the mocks."""
    image = Mock(id=501, generated_image_id=None)
    image_service = Mock()
    image_service.fast_ingest = AsyncMock(return_value=image)
    get_image_service = Mock(return_value=image_service)
    process_ingest = Mock()
    monkeypatch.setattr(image_service_module, "get_image_service", get_image_service)
    monkeypatch.setattr(tasks_module, "process_ingest", process_ingest)
    return Mock(image=image, image_service=image_service, get_image_service=get_image_service,
                process_ingest=process_ingest)


@pytest.mark.asyncio
async def test_generation_is_added_as_generated_library_image(library):
    db = _db()
    gen = Mock(id=12, user_id=7, generation_params={"prompt_extras": 1})

    result = await _service(db).add_to_library(gen, b"png-bytes")

    assert result is library.image
    library.get_image_service.assert_called_once_with(db, 7)
    library.image_service.fast_ingest.assert_awaited_once_with(
        file_data=b"png-bytes", filename="generated-12.png", source=ImageSource.GENERATED
    )
    assert library.image.generated_image_id == 12
    db.commit.assert_called_once_with()
    library.process_ingest.delay.assert_called_once_with(501, 7)


@pytest.mark.asyncio
async def test_edit_is_added_as_edited_library_image(library):
    gen = Mock(id=13, user_id=7, generation_params={"mode": "edit"})

    await _service(_db()).add_to_library(gen, b"bytes")

    library.image_service.fast_ingest.assert_awaited_once_with(
        file_data=b"bytes", filename="edited-13.png", source=ImageSource.EDITED
    )


@pytest.mark.asyncio
async def test_generation_already_in_library_is_skipped(library):
    gen = Mock(id=14, user_id=7, generation_params=None)

    assert await _service(_db(already_linked=True)).add_to_library(gen, b"bytes") is None

    library.image_service.fast_ingest.assert_not_awaited()
    library.process_ingest.delay.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_file_is_not_linked_or_ingested(library):
    library.image_service.fast_ingest.return_value = None
    db = _db()

    assert await _service(db).add_to_library(Mock(id=15, user_id=7, generation_params=None), b"x") is None

    db.commit.assert_not_called()
    library.process_ingest.delay.assert_not_called()


@pytest.mark.asyncio
async def test_library_failure_never_raises(library):
    library.image_service.fast_ingest.side_effect = RuntimeError("storage down")
    db = _db()

    assert await _service(db).add_to_library(Mock(id=16, user_id=7, generation_params=None), b"x") is None

    db.rollback.assert_called_once_with()
    library.process_ingest.delay.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_dispatch_failure_still_returns_image(library):
    library.process_ingest.delay.side_effect = RuntimeError("broker down")

    result = await _service(_db()).add_to_library(Mock(id=17, user_id=7, generation_params=None), b"x")

    assert result is library.image
