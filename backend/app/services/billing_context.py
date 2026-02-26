"""Thread-local billing context for passing user_id to write_log without modifying provider classes."""
import logging
import threading
import uuid

_ctx = threading.local()


def set_billing_user(user_id: int | None):
    """Set the billing user for the current thread."""
    _ctx.user_id = user_id


def get_billing_user() -> int | None:
    """Get the billing user for the current thread."""
    return getattr(_ctx, "user_id", None)


def set_billing_deferred(deferred: bool):
    """When True, usage records are created but balance debits are deferred."""
    _ctx.billing_deferred = deferred


def is_billing_deferred() -> bool:
    """Check if billing debits are currently deferred."""
    return getattr(_ctx, "billing_deferred", False)


def set_billing_image(image_id: int | None):
    """Set the image_id context so API call logs can reference the image."""
    _ctx.image_id = image_id


def get_billing_image() -> int | None:
    """Get the image_id for the current thread."""
    return getattr(_ctx, "image_id", None)


def set_billing_job(job_id: int | None):
    """Set the job_id context so API call logs can reference the job."""
    _ctx.job_id = job_id


def get_billing_job() -> int | None:
    """Get the job_id for the current thread."""
    return getattr(_ctx, "job_id", None)


def set_last_usage_record_id(record_id: int | None):
    """Store the ID of the most recently created UsageRecord for the current thread."""
    _ctx.last_usage_record_id = record_id


def get_last_usage_record_id() -> int | None:
    """Get the ID of the most recently created UsageRecord."""
    return getattr(_ctx, "last_usage_record_id", None)


def set_trace_id(trace_id: str | None):
    """Set the trace ID for the current thread."""
    _ctx.trace_id = trace_id


def get_trace_id() -> str | None:
    """Get the trace ID for the current thread."""
    return getattr(_ctx, "trace_id", None)


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
    _ctx.last_api_input_tokens = input_tokens
    _ctx.last_api_output_tokens = output_tokens
    _ctx.last_api_provider_cost = provider_cost


def get_last_api_call_tokens() -> tuple[int | None, int | None, float | None]:
    """Get token counts stored by the most recent API call."""
    return (
        getattr(_ctx, "last_api_input_tokens", None),
        getattr(_ctx, "last_api_output_tokens", None),
        getattr(_ctx, "last_api_provider_cost", None),
    )


def clear_last_api_call_tokens():
    """Clear stored token counts after orchestrator has consumed them."""
    _ctx.last_api_input_tokens = None
    _ctx.last_api_output_tokens = None
    _ctx.last_api_provider_cost = None


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
