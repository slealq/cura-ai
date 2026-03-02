"""OpenTelemetry setup — exports spans to Sentry via its OTel integration.

Must be called AFTER sentry_sdk.init() so Sentry hooks into the OTel pipeline.
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

        # Register SentrySpanProcessor so OTel spans export to Sentry.
        # Without this, TracerProvider has no processors and all spans
        # (provider_span, CeleryInstrumentor, etc.) are silently dropped.
        try:
            from sentry_sdk.integrations.opentelemetry import SentrySpanProcessor
            provider.add_span_processor(SentrySpanProcessor())
            logger.info("SentrySpanProcessor registered on TracerProvider")
        except (ImportError, Exception) as e:
            logger.debug(f"SentrySpanProcessor registration skipped: {e}")

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

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
        except (ImportError, Exception) as e:
            logger.debug(f"FastAPI instrumentation skipped: {e}")

    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        CeleryInstrumentor().instrument()
    except (ImportError, Exception) as e:
        logger.debug(f"Celery instrumentation skipped: {e}")


def get_tracer(name: str = "cura"):
    """Get an OTel tracer instance."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        return None
