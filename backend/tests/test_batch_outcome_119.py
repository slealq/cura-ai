from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models import JobStatus
from app.workers import generation_tasks as tasks


@pytest.mark.parametrize("task_name", ["batch_edit", "batch_generate"])
@pytest.mark.parametrize(
    "failed,expected_status,expected_return,provider_error",
    [
        (2, JobStatus.FAILED, "failed", None),
        (2, JobStatus.FAILED, "failed", "fal: content_policy_violation"),
        (1, JobStatus.COMPLETED, "success", None),
        (0, JobStatus.COMPLETED, "success", None),
    ],
)
def test_batch_outcome(monkeypatch, task_name, failed, expected_status, expected_return, provider_error):
    job = SimpleNamespace(
        status=JobStatus.PENDING,
        started_at=None,
        completed_at=None,
        total_items=0,
        progress=0,
        error_message=None,
        result=None,
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = job

    # First count: all images reached a terminal state.
    # Second count: number of failed images.
    db.query.return_value.filter.return_value.count.side_effect = [2, failed]
    db.query.return_value.filter.return_value.all.return_value = (
        [(provider_error,)] * failed if provider_error else [(None,)] * failed
    )

    monkeypatch.setattr(tasks, "_get_db", lambda: db)

    for name in [
        "_init_task_context",
        "write_log",
        "finalize_job_billing",
        "dispatch",
        "set_trace_id",
        "set_billing_user",
        "set_billing_job",
    ]:
        monkeypatch.setattr(tasks, name, MagicMock())

    monkeypatch.setattr(tasks.time, "sleep", MagicMock())

    result = getattr(tasks, task_name).run(
        [101, 102],
        job_id=8,
        user_id=7,
    )

    assert job.status == expected_status
    assert result["status"] == expected_return
    assert job.result == {
        "total": 2,
        "succeeded": 2 - failed,
        "failed": failed,
    }
    assert job.progress == 2
    assert job.completed_at is not None

    if failed == 2:
        assert job.error_message
        assert len(job.error_message) < 200
        if provider_error:
            assert "content policy" in job.error_message
            assert "content_policy_violation" not in job.error_message
    else:
        assert job.error_message is None

    tasks.finalize_job_billing.assert_called_once_with(db, 7, 8)
    assert tasks.dispatch.call_count == 2
    tasks.time.sleep.assert_not_called()


def test_mixed_failure_reasons_are_not_misclassified():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        ("fal: content_policy_violation",),
        ("fal: timeout",),
    ]

    reason = tasks._batch_failure_reason(db, [101, 102])

    assert reason == (
        "All generated images failed. "
        "Check individual image errors for details."
    )
