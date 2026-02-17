"""Job model for tracking pipeline processing jobs."""
import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class JobType(str, enum.Enum):
    """Type of processing job."""

    INGEST = "ingest"
    NORMALIZE = "normalize"
    TAG = "tag"
    DESCRIBE = "describe"
    EMBED = "embed"
    CLUSTER = "cluster"
    SUMMARIZE_CLUSTER = "summarize_cluster"
    FULL_PIPELINE = "full_pipeline"
    REPROCESS = "reprocess"
    BATCH_REPROCESS = "batch_reprocess"
    LORA_TRAIN = "lora_train"
    GENERATE_IMAGE = "generate_image"
    BATCH_GENERATE = "batch_generate"
    LORA_EVALUATE = "lora_evaluate"
    FOLDER_DELETE = "folder_delete"
    EDIT_IMAGE = "edit_image"
    BATCH_EDIT = "batch_edit"
    BATCH_DESCRIBE = "batch_describe"


class JobStatus(str, enum.Enum):
    """Status of a job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(Base):
    """Job model for tracking async processing tasks."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Job identification
    celery_task_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    job_type: Mapped[JobType] = mapped_column(
        Enum(JobType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Relationships
    image = relationship("Image", lazy="joined")

    # Status tracking
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, values_callable=lambda x: [e.value for e in x]),
        default=JobStatus.PENDING,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Parameters and results
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Logs
    logs: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_jobs_status_created", "status", "created_at"),
        Index("ix_jobs_type_status", "job_type", "status"),
    )
