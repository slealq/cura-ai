"""Hermetic unit tests for dispatch failure cleanup."""
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.models.generated_image import GenerationStatus
from app.models.job import JobStatus
from app.workers import dispatch as dispatch_module
from app.workers.dispatch import dispatch_or_fail


def test_dispatch_or_fail_returns_task_without_changing_records(monkeypatch):
    task = Mock()
    result = Mock()
    job = Mock(status="pending", error_message=None)
    generated_images = [Mock(status="pending", error_message=None)]
    db = Mock()
    monkeypatch.setattr(dispatch_module, "dispatch", Mock(return_value=result))

    actual = dispatch_or_fail(task, job, db, "argument", generated_images=generated_images)

    assert actual is result
    assert job.status == "pending"
    assert job.error_message is None
    assert generated_images[0].status == "pending"
    assert generated_images[0].error_message is None
    db.commit.assert_not_called()


def test_dispatch_or_fail_marks_records_failed_when_dispatch_raises(monkeypatch):
    job = Mock()
    generated_images = [Mock(), Mock()]
    db = Mock()
    monkeypatch.setattr(dispatch_module, "dispatch", Mock(side_effect=ConnectionError("broker unavailable")))

    with pytest.raises(HTTPException) as exc_info:
        dispatch_or_fail(Mock(), job, db, generated_images=generated_images)

    assert exc_info.value.status_code == 503
    assert job.status == JobStatus.FAILED
    assert job.error_message
    for generated_image in generated_images:
        assert generated_image.status == GenerationStatus.FAILED
        assert generated_image.error_message
    db.commit.assert_called_once()
