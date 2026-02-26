"""Thread-local billing context for passing user_id to write_log without modifying provider classes."""
import threading

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
