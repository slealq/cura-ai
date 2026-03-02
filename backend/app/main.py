"""FastAPI application entry point."""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import get_settings

# Configure logging with trace_id support — use a record factory so that
# every log record (including third-party loggers like uvicorn) gets trace_id.
from app.services.billing_context import get_trace_id

_original_record_factory = logging.getLogRecordFactory()


def _trace_record_factory(*args, **kwargs):
    record = _original_record_factory(*args, **kwargs)
    if not hasattr(record, "trace_id"):
        record.trace_id = get_trace_id() or "-"
    return record


logging.setLogRecordFactory(_trace_record_factory)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [trace=%(trace_id)s] %(message)s",
)
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
)

# Include API routes
app.include_router(api_router, prefix="/api")


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
    """Health check endpoint."""
    return {"status": "healthy"}


@app.on_event("startup")
async def startup():
    """Initialize on startup."""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")

    # Ensure storage directories exist
    from app.services.storage import get_storage_service
    get_storage_service()

    logger.info("Application started successfully")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Application shutting down")
