"""OpenTelemetry setup for distributed tracing and billing metrics.

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
    """Configure OpenTelemetry TracerProvider, MeterProvider, and auto-instrumentation.

    Args:
        service_name: Name for the service (e.g., "cura-api", "cura-worker").
        app: Optional FastAPI app instance for FastAPI instrumentation.
    """
    global _initialized
    if _initialized:
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        resource = Resource.create({"service.name": service_name})

        # TracerProvider
        tracer_provider = TracerProvider(resource=resource)
        trace.set_tracer_provider(tracer_provider)

        # MeterProvider — emits metrics consumed by Sentry or OTLP exporters
        meter_provider = MeterProvider(resource=resource)
        metrics.set_meter_provider(meter_provider)

        # Auto-instrument libraries
        _instrument_libraries(app)

        _initialized = True
        logger.info(f"OpenTelemetry initialized for {service_name} (tracing + metrics)")
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


def get_meter(name: str = "cura"):
    """Get an OTel meter instance."""
    try:
        from opentelemetry import metrics
        return metrics.get_meter(name)
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Billing meters — lazily initialised on first import of billing_meters
# ---------------------------------------------------------------------------

class _BillingMeters:
    """Lazy container for billing OTel instruments.

    Instruments are created on first access so the MeterProvider has time
    to initialise. If OTel is not installed, every attribute returns a
    no-op stub that accepts any call silently.
    """

    _meter = None
    _instruments: dict = {}

    _INSTRUMENT_DEFS: dict[str, tuple[str, str, str]] = {
        # name: (kind, otel_name, description)
        "decision_total": ("counter", "billing.decisions.total", "Total billing decisions created"),
        "decision_failed": ("counter", "billing.decisions.failed", "Billing decisions that failed"),
        "decision_cancelled": ("counter", "billing.decisions.cancelled", "Billing decisions cancelled"),
        "estimate_delta_pct": ("histogram", "billing.estimate_delta_pct", "Estimate vs actual delta percentage"),
        "charge_sparks": ("histogram", "billing.charge.sparks", "Charged sparks per operation"),
        "anomaly_total": ("counter", "billing.anomalies.total", "Total billing anomalies created"),
        "catalog_miss": ("counter", "billing.catalog_miss.total", "Catalog miss events"),
        "debit_latency_ms": ("histogram", "billing.debit.latency_ms", "Debit latency in milliseconds"),
        "reservation_sparks": ("histogram", "billing.reservation.amount_sparks", "Reserved sparks per decision"),
    }

    class _Noop:
        """Silent no-op for when OTel is unavailable."""
        def add(self, *a, **kw): pass
        def record(self, *a, **kw): pass

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        if name in self._instruments:
            return self._instruments[name]

        defn = self._INSTRUMENT_DEFS.get(name)
        if defn is None:
            raise AttributeError(f"No billing instrument named {name!r}")

        kind, otel_name, description = defn
        meter = self._get_meter()
        if meter is None:
            inst = self._Noop()
        elif kind == "counter":
            inst = meter.create_counter(otel_name, description=description)
        elif kind == "histogram":
            inst = meter.create_histogram(otel_name, description=description)
        else:
            inst = self._Noop()

        self._instruments[name] = inst
        return inst

    def _get_meter(self):
        if self._meter is None:
            self._meter = get_meter("billing")
        return self._meter


billing_meters = _BillingMeters()
