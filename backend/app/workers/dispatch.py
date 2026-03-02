"""Dispatch helper that auto-injects trace_id and session_id into Celery task calls.

Replaces direct `.delay()` calls so that correlation IDs flow from the API
request context into the Celery task without every call site needing to
pass them explicitly.
"""
from app.services.billing_context import get_session_id, get_trace_id


def dispatch(task, *args, **kwargs):
    """Dispatch a Celery task with trace_id and session_id from the current context.

    Usage:
        # Before:  tag_image.delay(image_id, user_id=uid)
        # After:   dispatch(tag_image, image_id, user_id=uid)
    """
    kwargs.setdefault("trace_id", get_trace_id())
    kwargs.setdefault("session_id", get_session_id())
    return task.delay(*args, **kwargs)
