"""A batch's children share its job, so a child must never finish that job."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import JobStatus
from app.workers import generation_tasks as tasks


def edit_mocks(monkeypatch, *, fails=False):
    params = dict(edit_model="nano-banana-2.1-edit", mode="edit")
    generation = SimpleNamespace(id=1, prompt="change", negative_prompt=None, base_model=params["edit_model"], generation_params=params, status=None, error_message=None, history=None)
    service = SimpleNamespace(get_generated_image=lambda i: generation, save_generated_result=AsyncMock(), create_generated_image=MagicMock())
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = generation
    update = MagicMock()
    monkeypatch.setattr(tasks, "_get_db", lambda: db)
    monkeypatch.setattr(tasks, "_update_job_status", update)
    for name in ["_init_task_context", "write_log", "finalize_job_billing"]:
        monkeypatch.setattr(tasks, name, MagicMock())
    monkeypatch.setattr(tasks, "get_generation_service", lambda *args: service)
    monkeypatch.setattr(tasks, "_resolve_edit_sources", lambda *args: ["data:image/png;base64,eA=="])
    result = SimpleNamespace(images=[b"image"], widths=[512], heights=[512], seed=1, metadata={})
    editor = SimpleNamespace(edit=AsyncMock(side_effect=RuntimeError("fal failed") if fails else None, return_value=result))
    monkeypatch.setattr(tasks, "get_editor", lambda **kwargs: editor)
    billing = MagicMock()
    billing.__enter__.return_value = billing
    billing.skipped = False
    billing.call.side_effect = lambda fn, *args: fn(*args)
    monkeypatch.setattr(tasks, "billable", lambda *args, **kwargs: billing)
    monkeypatch.setattr("app.services.image_history.safe_snapshot", lambda *args: dict(inputs=[]))
    return update


def statuses(update):
    return [call.args[2] for call in update.call_args_list]


def test_batch_child_leaves_the_shared_job_running(monkeypatch):
    update = edit_mocks(monkeypatch)
    tasks.edit_image.run(1, job_id=8, user_id=7, from_batch=True)
    assert JobStatus.COMPLETED not in statuses(update)


def test_failed_batch_child_leaves_the_shared_job_running(monkeypatch):
    update = edit_mocks(monkeypatch, fails=True)
    with pytest.raises(RuntimeError):
        tasks.edit_image.run(1, job_id=8, user_id=7, from_batch=True)
    assert JobStatus.FAILED not in statuses(update)


def test_single_edit_still_finishes_its_own_job(monkeypatch):
    update = edit_mocks(monkeypatch)
    tasks.edit_image.run(1, job_id=8, user_id=7)
    assert JobStatus.COMPLETED in statuses(update)


@pytest.mark.parametrize("task, child", [("batch_edit", "edit_image"), ("batch_generate", "generate_image")])
def test_batch_stops_waiting_when_its_job_was_failed(monkeypatch, task, child):
    job = SimpleNamespace(status=JobStatus.PENDING, error_message="Stuck", started_at=None, total_items=0)
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job
    monkeypatch.setattr(tasks, "_get_db", lambda: db)
    for name in ["_init_task_context", "write_log", "finalize_job_billing"]:
        monkeypatch.setattr(tasks, name, MagicMock())
    fail = MagicMock()
    monkeypatch.setattr(tasks, "_fail_unfinished_images", fail)

    def dispatch(*args, **kwargs):
        job.status = JobStatus.FAILED

    monkeypatch.setattr(tasks, "dispatch", dispatch)
    result = getattr(tasks, task).run([1, 2], job_id=8, user_id=7)
    assert result["status"] == "failed"
    fail.assert_called_once_with(db, [1, 2], "Stuck")
