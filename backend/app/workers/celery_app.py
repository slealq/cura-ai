"""Celery application configuration."""
import logging
import ssl

from celery import Celery
from celery.signals import worker_ready

from app.core.config import get_settings

logger = logging.getLogger(__name__)

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
    },
)


@worker_ready.connect
def recover_stuck_training_jobs(sender, **kwargs):
    """On worker startup, re-dispatch polling for LoRA models stuck in TRAINING with a request_id."""
    # Only run on the generation queue worker
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
            if not request_id:
                logger.warning(
                    f"LoRA {lora.id} stuck in TRAINING but has no request_id — cannot recover automatically"
                )
                continue

            logger.info(
                f"Recovering stuck LoRA training: id={lora.id} name={lora.name!r} request_id={request_id}"
            )
            # Re-dispatch train_lora which will detect TRAINING + request_id and resume polling
            from app.workers.generation_tasks import train_lora
            train_lora.delay(lora.id, lora.job_id, lora.user_id)

        if stuck:
            logger.info(f"Recovery: re-dispatched {len(stuck)} stuck LoRA training job(s)")
    except Exception as e:
        logger.error(f"Failed to recover stuck training jobs on startup: {e}")
    finally:
        db.close()
