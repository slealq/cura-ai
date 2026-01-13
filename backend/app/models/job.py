"""Job model for tracking pipeline processing jobs."""
import enum
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

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

    # Job identification
    celery_task_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    job_type: Mapped[JobType] = mapped_column(Enum(JobType), nullable=False)

    # Status tracking
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.PENDING, nullable=False
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
