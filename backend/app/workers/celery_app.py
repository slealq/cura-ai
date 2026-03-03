"""Celery application configuration."""
import logging
import ssl

from celery import Celery
from celery.signals import setup_logging, worker_process_init, worker_ready

from app.core.config import get_settings

logger = logging.getLogger(__name__)


@setup_logging.connect
def configure_worker_logging(**kwargs):
    """Configure Celery worker logging with trace_id + session_id."""
    from app.core.logging_config import configure_logging
    configure_logging("cura-worker")

settings = get_settings()

# Azure Redis requires TLS (rediss:// URLs) — configure SSL for Celery broker/backend
_broker_ssl = {"ssl_cert_reqs": ssl.CERT_REQUIRED} if settings.celery_broker_url.startswith("rediss://") else None
_backend_ssl = {"ssl_cert_reqs": ssl.CERT_REQUIRED} if settings.celery_result_backend.startswith("rediss://") else None

celery_app = Celery(
    "design_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks",
        "app.workers.generation_tasks",
    ],
)

# Disable mingle (worker-to-worker sync at startup) — causes KeyError crashes
# in kombu Redis transport when multiple workers start simultaneously and
# race on file descriptor tracking.
celery_app.steps['consumer'].discard('celery.worker.consumer.mingle:Mingle')

celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task execution settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,

    # Result settings
    result_expires=86400,  # 24 hours

    # Rate limiting
    task_annotations={
        "app.workers.tasks.tag_image": {"rate_limit": "30/m"},
        "app.workers.tasks.describe_image": {"rate_limit": "30/m"},
        "app.workers.tasks.embed_image": {"rate_limit": "60/m"},
        "app.workers.generation_tasks.generate_image": {"rate_limit": "20/m"},
        "app.workers.generation_tasks.edit_image": {"rate_limit": "20/m"},
    },

    # Routing
    task_routes={
        "app.workers.tasks.cluster_all_images": {"queue": "clustering"},
        "app.workers.tasks.summarize_clusters": {"queue": "clustering"},
        "app.workers.generation_tasks.train_lora": {"queue": "generation"},
        "app.workers.generation_tasks.generate_image": {"queue": "generation"},
        "app.workers.generation_tasks.batch_generate": {"queue": "generation"},
        "app.workers.generation_tasks.evaluate_lora": {"queue": "generation"},
        "app.workers.generation_tasks.download_lora_weights": {"queue": "generation"},
        "app.workers.generation_tasks.edit_image": {"queue": "generation"},
        "app.workers.generation_tasks.batch_edit": {"queue": "generation"},
    },

    # SSL for Azure Redis TLS (no-op when using local redis://)
    broker_use_ssl=_broker_ssl,
    redis_backend_use_ssl=_backend_ssl,

    # Broker connection resilience (Azure Redis can drop idle TLS connections)
    broker_transport_options={
        "socket_timeout": 30,
        "socket_connect_timeout": 30,
        "retry_on_timeout": True,
    },
    broker_connection_retry_on_startup=True,

    # Beat schedule
    beat_schedule={
        "cleanup-pipeline-logs": {
            "task": "app.workers.tasks.cleanup_old_pipeline_logs",
            "schedule": 86400.0,  # once per day
        },
        "cleanup-stale-reservations": {
            "task": "app.workers.tasks.cleanup_stale_reservations",
            "schedule": 3600.0,  # once per hour
        },
        "monitor-queue-health": {
            "task": "app.workers.tasks.monitor_queue_health",
            "schedule": 60.0,  # once per minute
        },
    },
)


# CeleryIntegration (configured in sentry_config.py with propagate_traces=True)
# automatically creates a consumer-side transaction via its _wrap_tracer function:
#   1. Extracts sentry-trace/baggage headers from the Celery message
#   2. Calls continue_trace() to link to the API request trace
#   3. Wraps task execution in start_transaction(op="queue.task.celery")
# Sentry-native integrations (sqlalchemy, redis, httpx) create child spans
# for DB queries, cache ops, and HTTP calls automatically.


def _rebuild_celery_tracer_cache():
    """Rebuild Celery's task.__trace__ cache with the Sentry-patched build_tracer.

    In prefork pool, Celery's process_initializer builds and caches tracer
    functions for all tasks BEFORE firing worker_process_init. Since we defer
    sentry_sdk.init() to that signal (DSN is stored in DB, not env vars),
    CeleryIntegration's _patch_build_tracer replaces build_tracer too late —
    the cache already has un-wrapped tracers. This function rebuilds the cache
    so _wrap_tracer creates queue.task.celery transactions on the consumer side.
    """
    try:
        import celery.app.trace as celery_trace
        from celery import current_app

        if "sentry" not in str(celery_trace.build_tracer):
            logger.warning("build_tracer not patched by Sentry — skipping cache rebuild")
            return

        hostname = celery_trace._localized[2] if celery_trace._localized else None
        rebuilt = 0
        for name, task in current_app.tasks.items():
            task.__trace__ = celery_trace.build_tracer(
                name, task, current_app.loader, hostname, app=current_app,
            )
            rebuilt += 1

        logger.info(f"Rebuilt Celery tracer cache for {rebuilt} tasks (Sentry-wrapped)")
    except Exception as e:
        logger.warning(f"Failed to rebuild Celery tracer cache: {e}")


_sentry_initialized = False


def _init_sentry_and_otel():
    """Initialize Sentry SDK + OTel in the current process.

    Must run in the process where tasks actually execute. For prefork pool
    that's each child process (worker_process_init signal). For solo pool
    it's the main process (worker_ready signal).
    """
    global _sentry_initialized
    if _sentry_initialized:
        return
    _sentry_initialized = True

    try:
        from app.db.base import SessionLocal
        from app.models.api_key import APIKey
        from app.services.encryption import decrypt_api_key

        db = SessionLocal()
        try:
            key = db.query(APIKey).filter(APIKey.provider == "sentry", APIKey.status == "active").first()
            if not key:
                logger.info("Sentry DSN not configured — skipping Sentry init in worker")
                return
            dsn = decrypt_api_key(key.encrypted_key)
        finally:
            db.close()

        import sentry_sdk

        from app.core.config import get_settings as _get_settings
        from app.core.sentry_config import get_sentry_init_kwargs
        sentry_sdk.init(
            dsn=dsn,
            environment=_get_settings().environment,
            # TEMPORARY: 1.0 for 2 weeks to baseline worker traces.
            # Reduce to 0.2 after baseline data is collected.
            traces_sample_rate=1.0,
            **get_sentry_init_kwargs(),
        )
        logger.info("Sentry SDK initialized in Celery worker (logs enabled)")

        # Rebuild Celery's tracer cache so it uses the Sentry-patched build_tracer.
        # In prefork pool, process_initializer builds task.__trace__ for ALL tasks
        # BEFORE firing worker_process_init. By the time sentry_sdk.init() patches
        # build_tracer, the cache already has un-wrapped tracers. Rebuilding here
        # ensures _wrap_tracer creates queue.task.celery transactions.
        _rebuild_celery_tracer_cache()

        # Initialize OpenTelemetry (must be after Sentry so spans export to Sentry)
        from app.core.otel import configure_otel
        configure_otel("cura-worker")
    except Exception as e:
        logger.warning(f"Failed to initialize Sentry/OTel in worker: {e}")


@worker_process_init.connect
def init_sentry_in_child_process(**kwargs):
    """Initialize Sentry + OTel in each prefork child process.

    worker_process_init fires in each child process of the prefork pool,
    which is where tasks actually execute. Without this, sentry_sdk.init()
    only runs in the main process (via worker_ready) AFTER forking, so
    child processes have no CeleryIntegration and trace propagation breaks.
    """
    _init_sentry_and_otel()


@worker_ready.connect
def init_sentry_on_worker(sender, **kwargs):
    """Fallback: initialize Sentry in the main process for solo/threads pool."""
    _init_sentry_and_otel()


@worker_ready.connect
def log_stuck_training_jobs(sender, **kwargs):
    """On worker startup, log any LoRA models stuck in TRAINING status.

    Training is expensive and must only be triggered by explicit user action.
    Stuck models should be recovered via the /lora/{id}/recover API endpoint.
    We intentionally do NOT auto-dispatch training tasks on worker restart.
    """
    queues = [q.name for q in sender.task_consumer.queues] if hasattr(sender, 'task_consumer') else []
    if queues and "generation" not in queues:
        return

    from app.db.base import SessionLocal
    from app.models.lora_model import LoraModel, LoraModelStatus

    db = SessionLocal()
    try:
        stuck = (
            db.query(LoraModel)
            .filter(LoraModel.status == LoraModelStatus.TRAINING)
            .all()
        )
        for lora in stuck:
            request_id = (lora.provider_metadata or {}).get("request_id")
            logger.warning(
                f"LoRA {lora.id} ({lora.name!r}) stuck in TRAINING "
                f"(request_id={request_id or 'none'}). "
                f"Use POST /generation/lora/{lora.id}/recover to resume."
            )
        if stuck:
            logger.warning(
                f"Found {len(stuck)} stuck LoRA training job(s). "
                f"They will NOT be auto-recovered — use the /recover endpoint."
            )
    except Exception as e:
        logger.error(f"Failed to check stuck training jobs on startup: {e}")
    finally:
        db.close()
