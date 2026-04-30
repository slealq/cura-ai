"""FastAPI application entry point."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.api.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.core.logging_config import configure_logging
from app.middleware.request_context import RequestContextMiddleware

configure_logging("cura-api")
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Design Idea Ingestion Pipeline - Automatically ingest, tag, and cluster design inspiration images",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id", "X-Request-Id"],
)

# Request context middleware — sets trace_id + request_id on every request.
# Added after CORS so it executes first (ASGI: last added = first executed).
app.add_middleware(RequestContextMiddleware)

# Include API routes
app.include_router(api_router, prefix="/api")

# Webhook routes (no /api prefix — external providers call these directly)
app.include_router(webhooks_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/api/docs",
    }


@app.get("/health")
async def health():
    """Health check with dependency verification (DB, Redis, storage)."""
    checks = {}

    # Database check
    try:
        from sqlalchemy import text

        from app.db.base import engine
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis check
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
        r.ping()
        r.close()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # Storage check
    try:
        from app.services.storage import get_storage_service
        svc = get_storage_service()
        if settings.storage_backend == "azure":
            svc._container_client.get_container_properties()
        elif settings.storage_backend == "local":
            import os
            if not os.path.isdir(svc.local_path):
                raise FileNotFoundError(f"Storage dir missing: {svc.local_path}")
        checks["storage"] = "ok"
    except Exception as e:
        checks["storage"] = f"error: {e}"

    status = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


def _init_sentry():
    """Initialize Sentry SDK from DSN stored in the database."""
    try:
        from app.db.base import SessionLocal
        from app.models.api_key import APIKey
        from app.services.encryption import decrypt_api_key

        db = SessionLocal()
        try:
            key = db.query(APIKey).filter(APIKey.provider == "sentry", APIKey.status == "active").first()
            if not key:
                logger.info("Sentry DSN not configured — skipping Sentry init")
                return
            dsn = decrypt_api_key(key.encrypted_key)
        finally:
            db.close()

        import sentry_sdk

        from app.core.sentry_config import get_sentry_init_kwargs
        sentry_sdk.init(
            dsn=dsn,
            environment=settings.environment,
            # TEMPORARY: 1.0 for 2 weeks to baseline backend traces.
            # Reduce to 0.2 after baseline data is collected.
            traces_sample_rate=1.0,
            **get_sentry_init_kwargs(),
        )
        logger.info("Sentry SDK initialized (logs enabled)")
    except Exception as e:
        logger.warning(f"Failed to initialize Sentry: {e}")


@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Ensure storage directories exist
    from app.services.storage import get_storage_service
    get_storage_service()

    # Initialize Sentry from DB-stored DSN
    _init_sentry()

    # Initialize OpenTelemetry (must be after Sentry so spans export to Sentry)
    from app.core.otel import configure_otel
    configure_otel("cura-api", app=app)

    # Validate model registry against cost catalog
    _validate_model_registry()

    logger.info("Application started successfully")


def _validate_model_registry():
    """Cross-check model registry entries against CostCatalog rows."""
    try:
        from app.db.base import SessionLocal
        from app.services.model_registry import all_entries, validate_against_catalog

        db = SessionLocal()
        try:
            errors = validate_against_catalog(db)
            count = len(all_entries())
            if errors:
                for err in errors:
                    logger.warning(f"Model registry: {err}")
                try:
                    import sentry_sdk as _sentry
                    _sentry.capture_message(
                        f"Model registry validation: {len(errors)} issue(s)",
                        level="warning",
                    )
                except Exception:
                    pass
            logger.info(
                "Model registry validated: %d models, %d issue(s)",
                count, len(errors),
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning(f"Model registry validation failed: {e}")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Application shutting down")
