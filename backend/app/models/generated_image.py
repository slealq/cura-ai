"""Generated image model for tracking AI-generated images."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GenerationStatus(str, enum.Enum):
    """Status of an image generation."""

    PENDING = "pending"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class GeneratedImage(Base):
    """AI-generated image record."""

    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Prompt
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Model
    base_model: Mapped[str] = mapped_column(String(128), nullable=False)
    generation_provider: Mapped[str] = mapped_column(String(64), nullable=False)

    # LoRA
    lora_model_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("lora_models.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lora_scale: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Generation params
    generation_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[GenerationStatus] = mapped_column(
        Enum(GenerationStatus, native_enum=False, length=32), default=GenerationStatus.PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result
    object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Thumbnails
    thumbnail_uri_small: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_uri_medium: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provider metadata
    provider_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Job tracking
    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    lora_model = relationship("LoraModel", back_populates="generations")
    job = relationship("Job", lazy="joined")

    __table_args__ = (
        Index("ix_generated_images_status", "status"),
        Index("ix_generated_images_created_at", "created_at"),
    )
