"""OpenTelemetry setup for distributed tracing.

NOTE on Sentry integration (sentry-sdk 2.x):
  With instrumenter="sentry" (the default), SentrySpanProcessor is a no-op —
  all OTel spans are silently dropped. Sentry-native integrations (sqlalchemy,
  redis, httpx, celery) handle span creation instead. The OTel TracerProvider
  and instrumentors here are kept for:
    1. Future migration to OTLPIntegration (which exports OTel spans to Sentry)
    2. Any non-Sentry OTel consumers (Jaeger, Zipkin, etc.)
    3. Manual tracer usage via get_tracer()

  To enable OTel → Sentry export, add OTLPIntegration to sentry_config.py:
    from sentry_sdk.integrations.otlp import OTLPIntegration
    integrations.append(OTLPIntegration())
"""
import logging

logger = logging.getLogger(__name__)

_initialized = False


def configure_otel(service_name: str, app=None) -> None:
    """Configure OpenTelemetry TracerProvider and auto-instrumentation.

    Args:
        service_name: Name for the service (e.g., "cura-api", "cura-worker").
        app: Optional FastAPI app instance for FastAPI instrumentation.
    """
    global _initialized
    if _initialized:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(provider)

        # Auto-instrument libraries
        _instrument_libraries(app)

        _initialized = True
        logger.info(f"OpenTelemetry initialized for {service_name}")
    except ImportError:
        logger.info("OpenTelemetry SDK not installed — skipping OTel init")
    except Exception as e:
        logger.warning(f"Failed to initialize OpenTelemetry: {e}")


def _instrument_libraries(app=None) -> None:
    """Auto-instrument supported libraries."""
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        from app.db.base import engine
        SQLAlchemyInstrumentor().instrument(engine=engine)
    except (ImportError, Exception) as e:
        logger.debug(f"SQLAlchemy instrumentation skipped: {e}")

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
    except (ImportError, Exception) as e:
        logger.debug(f"Redis instrumentation skipped: {e}")

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except (ImportError, Exception) as e:
        logger.debug(f"HTTPX instrumentation skipped: {e}")

    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()
    except (ImportError, Exception) as e:
        logger.debug(f"Requests instrumentation skipped: {e}")

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except (ImportError, Exception) as e:
            logger.debug(f"FastAPI instrumentation skipped: {e}")

    # NOTE: CeleryInstrumentor intentionally NOT used here.
    # CeleryIntegration (sentry_config.py) handles trace propagation and
    # consumer-side transaction creation. CeleryInstrumentor would conflict
    # by also patching apply_async() and wrapping task execution.


def get_tracer(name: str = "cura"):
    """Get an OTel tracer instance."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return None
