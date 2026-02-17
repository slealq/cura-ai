"""Thread-local billing context for passing user_id to write_log without modifying provider classes."""
import threading

_ctx = threading.local()


def set_billing_user(user_id: int | None):
    """Set the billing user for the current thread."""
    _ctx.user_id = user_id


def get_billing_user() -> int | None:
    """Get the billing user for the current thread."""
    return getattr(_ctx, "user_id", None)
