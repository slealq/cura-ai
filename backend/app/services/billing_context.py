"""Async-safe billing context using contextvars for passing user_id, trace_id,
and other request/task-scoped state to write_log and providers without modifying
their signatures.

Uses contextvars.ContextVar instead of threading.local() so that context is
correctly isolated per async task (FastAPI) and per process (Celery prefork).
"""
import logging
import uuid
from contextvars import ContextVar

_user_id_var: ContextVar[int | None] = ContextVar("billing_user_id", default=None)
_billing_deferred_var: ContextVar[bool] = ContextVar("billing_deferred", default=False)
_image_id_var: ContextVar[int | None] = ContextVar("billing_image_id", default=None)
_job_id_var: ContextVar[int | None] = ContextVar("billing_job_id", default=None)
_last_usage_record_id_var: ContextVar[int | None] = ContextVar(
    "last_usage_record_id", default=None
)
_trace_id_var: ContextVar[str | None] = ContextVar("trace_id", default=None)
_last_api_input_tokens_var: ContextVar[int | None] = ContextVar(
    "last_api_input_tokens", default=None
)
_last_api_output_tokens_var: ContextVar[int | None] = ContextVar(
    "last_api_output_tokens", default=None
)
_last_api_provider_cost_var: ContextVar[float | None] = ContextVar(
    "last_api_provider_cost", default=None
)


def set_billing_user(user_id: int | None):
    """Set the billing user for the current context."""
    _user_id_var.set(user_id)


def get_billing_user() -> int | None:
    """Get the billing user for the current context."""
    return _user_id_var.get()


def set_billing_deferred(deferred: bool):
    """When True, usage records are created but balance debits are deferred."""
    _billing_deferred_var.set(deferred)


def is_billing_deferred() -> bool:
    """Check if billing debits are currently deferred."""
    return _billing_deferred_var.get()


def set_billing_image(image_id: int | None):
    """Set the image_id context so API call logs can reference the image."""
    _image_id_var.set(image_id)


def get_billing_image() -> int | None:
    """Get the image_id for the current context."""
    return _image_id_var.get()


def set_billing_job(job_id: int | None):
    """Set the job_id context so API call logs can reference the job."""
    _job_id_var.set(job_id)


def get_billing_job() -> int | None:
    """Get the job_id for the current context."""
    return _job_id_var.get()


def set_last_usage_record_id(record_id: int | None):
    """Store the ID of the most recently created UsageRecord for the current context."""
    _last_usage_record_id_var.set(record_id)


def get_last_usage_record_id() -> int | None:
    """Get the ID of the most recently created UsageRecord."""
    return _last_usage_record_id_var.get()


def set_trace_id(trace_id: str | None):
    """Set the trace ID for the current context."""
    _trace_id_var.set(trace_id)


def get_trace_id() -> str | None:
    """Get the trace ID for the current context."""
    return _trace_id_var.get()


def init_trace() -> str:
    """Generate a new trace ID, store in context, and return it."""
    trace_id = uuid.uuid4().hex
    set_trace_id(trace_id)
    return trace_id


def set_last_api_call_tokens(
    input_tokens: int | None,
    output_tokens: int | None,
    provider_cost: float | None = None,
):
    """Store token counts from the most recent API call for orchestrator pickup."""
    _last_api_input_tokens_var.set(input_tokens)
    _last_api_output_tokens_var.set(output_tokens)
    _last_api_provider_cost_var.set(provider_cost)


def get_last_api_call_tokens() -> tuple[int | None, int | None, float | None]:
    """Get token counts stored by the most recent API call."""
    return (
        _last_api_input_tokens_var.get(),
        _last_api_output_tokens_var.get(),
        _last_api_provider_cost_var.get(),
    )


def clear_last_api_call_tokens():
    """Clear stored token counts after orchestrator has consumed them."""
    _last_api_input_tokens_var.set(None)
    _last_api_output_tokens_var.set(None)
    _last_api_provider_cost_var.set(None)


def make_idempotency_key(
    user_id: int,
    trace_id: str | None,
    operation: str,
    resource_id: int | str | None = None,
) -> str:
    """Build a deterministic idempotency key for deduplication."""
    parts = [str(user_id), trace_id or "notrace", operation]
    if resource_id is not None:
        parts.append(str(resource_id))
    return ":".join(parts)


class TraceIdFilter(logging.Filter):
    """Logging filter that injects trace_id from billing context into log records."""

    def filter(self, record):
        record.trace_id = get_trace_id() or "-"
        return True
