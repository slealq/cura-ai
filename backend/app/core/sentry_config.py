"""Shared Sentry configuration for API and Celery workers.

Provides common integrations and log filtering so both init paths
stay consistent.
"""
import logging


def get_sentry_init_kwargs():
    """Return shared kwargs for sentry_sdk.init().

    Caller is responsible for providing dsn, environment, and
    traces_sample_rate — this returns the logging-related config.
    """
    from sentry_sdk.integrations.logging import LoggingIntegration

    return {
        "send_default_pii": False,
        "enable_logs": True,
        "before_send_log": _before_send_log,
        "integrations": [
            LoggingIntegration(
                level=logging.INFO,
                event_level=logging.ERROR,
                sentry_logs_level=logging.INFO,
            ),
        ],
    }


def _before_send_log(log, _hint):
    """Filter noisy logs before sending to Sentry."""
    body = log.get("body", "")
    if "/health" in body:
        return None
    if "mingle" in body.lower() or "gossip" in body.lower():
        return None
    return log
