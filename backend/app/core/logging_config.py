"""Shared logging configuration for API and Celery workers.

Detects TTY vs Docker (non-TTY) and switches between human-readable and JSON
log formats. Injects trace_id and session_id from contextvars into every log
record via a custom record factory.
"""
import logging
import sys

from app.services.billing_context import get_session_id, get_trace_id


def configure_logging(service_name: str = "cura") -> None:
    """Configure logging for the application.

    - TTY (local dev): human-readable format with [trace=X sess=Y]
    - Non-TTY (Docker): JSON format via python-json-logger
    """
    _original_factory = logging.getLogRecordFactory()

    def _record_factory(*args, **kwargs):
        record = _original_factory(*args, **kwargs)
        record.trace_id = get_trace_id() or "-"
        record.session_id = get_session_id() or "-"
        record.service = service_name
        return record

    logging.setLogRecordFactory(_record_factory)

    is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    if is_tty:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - [trace=%(trace_id)s sess=%(session_id)s] %(message)s",
            force=True,
        )
    else:
        try:
            from pythonjsonlogger import json as jsonlogger

            handler = logging.StreamHandler()
            formatter = jsonlogger.JsonFormatter(
                fmt="%(asctime)s %(name)s %(levelname)s %(message)s %(trace_id)s %(session_id)s %(service)s",
                rename_fields={"asctime": "timestamp", "name": "logger", "levelname": "level"},
            )
            handler.setFormatter(formatter)
            logging.root.handlers.clear()
            logging.root.addHandler(handler)
            logging.root.setLevel(logging.INFO)
        except ImportError:
            # Fallback if python-json-logger not installed
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s - %(name)s - %(levelname)s - [trace=%(trace_id)s sess=%(session_id)s] %(message)s",
                force=True,
            )
