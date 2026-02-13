"""LoRA model for tracking trained LoRA adapters."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class LoraModelStatus(str, enum.Enum):
    """Status of a LoRA training job."""

    PENDING = "pending"
    TRAINING = "training"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class LoraModel(Base):
    """LoRA model trained from a folder of images."""

    __tablename__ = "lora_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Identity
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    trigger_word: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source
    folder_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cluster_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Training config
    base_model: Mapped[str] = mapped_column(String(128), default="flux-dev", nullable=False)
    training_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    training_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[LoraModelStatus] = mapped_column(
        Enum(LoraModelStatus, native_enum=False, length=32), default=LoraModelStatus.PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result
    lora_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    lora_local_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    training_images_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Provider metadata
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Job tracking
    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    training_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    training_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    folder = relationship("Folder", lazy="joined")
    cluster = relationship("Cluster", lazy="joined")
    job = relationship("Job", lazy="joined")
    generations: Mapped[list["GeneratedImage"]] = relationship(
        "GeneratedImage", back_populates="lora_model"
    )
    evaluations: Mapped[list["LoraEvaluation"]] = relationship(
        "LoraEvaluation", back_populates="lora_model", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_lora_models_status", "status"),
    )
