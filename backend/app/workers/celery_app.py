"""Celery application configuration."""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "design_pipeline",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.tasks",
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
    },

    # Routing
    task_routes={
        "app.workers.tasks.cluster_all_images": {"queue": "clustering"},
        "app.workers.tasks.summarize_clusters": {"queue": "clustering"},
    },

    # Beat schedule
    beat_schedule={
        "cleanup-pipeline-logs": {
            "task": "app.workers.tasks.cleanup_old_pipeline_logs",
            "schedule": 86400.0,  # once per day
        },
    },
)
