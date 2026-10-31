"""Bounded, payload-free errors suitable for persistence and display."""
import re

MAX_ERROR_LENGTH = 2000
_DATA_URL = re.compile(r"data:[^\s,\"']*;base64,[A-Za-z0-9+/=_-]*", re.IGNORECASE)
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_-]{256,}")


def readable_error(error) -> str:
    """Unwrap retry errors, redact inline images, and bound provider responses."""
    if hasattr(error, "last_attempt"):
        try:
            error.last_attempt.result()
        except Exception as inner:
            error = inner
    message = str(error).strip() if error is not None else ""
    message = message or (type(error).__name__ if isinstance(error, Exception) else "Processing failed; no error details were provided")
    message = _DATA_URL.sub("[image payload removed]", message)
    message = _LONG_TOKEN.sub("[payload removed]", message)
    if len(message) > MAX_ERROR_LENGTH:
        message = message[:MAX_ERROR_LENGTH - 14] + "… [truncated]"
    return message


def safe_details(value):
    """Sanitize nested log details without changing their structure."""
    if isinstance(value, str):
        return readable_error(value) if value else value
    if isinstance(value, dict):
        return {key: safe_details(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_details(item) for item in value]
    return value
