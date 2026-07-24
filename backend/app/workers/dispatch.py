"""Dispatch helper that auto-injects trace_id and session_id into Celery task calls.

Replaces direct `.delay()` calls so that correlation IDs flow from the API
request context into the Celery task without every call site needing to
pass them explicitly.
"""
import logging

from fastapi import HTTPException

from app.models.generated_image import GenerationStatus
from app.models.job import JobStatus
from app.services.billing_context import get_session_id, get_trace_id

logger = logging.getLogger(__name__)


def dispatch(task, *args, **kwargs):
    """Dispatch a Celery task with trace_id and session_id from the current context.

    Uses app.send_task() instead of task.delay() to avoid duplicate
    queue.submit.celery spans — CeleryIntegration wraps both Task.apply_async
    and Celery.send_task with _wrap_task_run, and apply_async calls send_task
    internally, creating two identical spans in the Sentry waterfall.

    Usage:
        # Before:  tag_image.delay(image_id, user_id=uid)
        # After:   dispatch(tag_image, image_id, user_id=uid)
    """
    kwargs.setdefault("trace_id", get_trace_id())
    kwargs.setdefault("session_id", get_session_id())
    return task.app.send_task(task.name, args=args, kwargs=kwargs)


def dispatch_or_fail(task, job, db, *args, generated_images=None, **kwargs):
    """Dispatch a task or mark its committed records failed before re-raising.

    Use after committing a Job and, optionally, GeneratedImage records so a
    broker failure cannot leave them permanently pending.
    """
    try:
        return dispatch(task, *args, **kwargs)
    except Exception as e:
        logger.error("Failed to dispatch job: %s", e)
        job.status = JobStatus.FAILED
        job.error_message = f"Failed to dispatch job: {e}"
        for gen in generated_images or []:
            gen.status = GenerationStatus.FAILED
            gen.error_message = "Failed to dispatch job"
        db.commit()
        raise HTTPException(status_code=503, detail="Failed to start job — please try again.") from e
