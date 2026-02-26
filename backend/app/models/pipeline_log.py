"""Pipeline debug log entries."""
import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LogLevel(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class LogCategory(str, enum.Enum):
    API_CALL = "api_call"
    TASK = "task"
    PIPELINE = "pipeline"
    SYSTEM = "system"


class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    # Classification — values_callable ensures SQLAlchemy uses enum values (lowercase)
    # to match the PostgreSQL enum type created in the migration
    level: Mapped[LogLevel] = mapped_column(
        Enum(LogLevel, values_callable=lambda x: [e.value for e in x]),
        nullable=False, default=LogLevel.INFO,
    )
    category: Mapped[LogCategory] = mapped_column(
        Enum(LogCategory, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )

    # Context (plain ints, no FK — keeps log writes independent)
    image_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    task_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Message
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # External API call details (populated only for category=api_call)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    operation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # Overflow / extra context
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Billing tracking
    billing_failed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_pipeline_logs_category_created", "category", "created_at"),
        Index("ix_pipeline_logs_level_created", "level", "created_at"),
    )
