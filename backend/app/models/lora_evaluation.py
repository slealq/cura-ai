"""LoRA evaluation models for tracking model quality assessments."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EvaluationStatus(str, enum.Enum):
    """Status of an evaluation run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class LoraEvaluation(Base):
    """One evaluation run for a LoRA model."""

    __tablename__ = "lora_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Link to LoRA model
    lora_model_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lora_models.id", ondelete="CASCADE"), nullable=False
    )

    # Config
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Status
    status: Mapped[EvaluationStatus] = mapped_column(
        Enum(EvaluationStatus, native_enum=False, length=32),
        default=EvaluationStatus.PENDING,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Aggregated scores
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_embedding_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_vision_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_clip_image_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_clip_text_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Assessment
    assessment_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    aggregate_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Job tracking
    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    lora_model = relationship("LoraModel", back_populates="evaluations", lazy="joined")
    job = relationship("Job", lazy="joined")
    pairs: Mapped[list["EvaluationPair"]] = relationship(
        "EvaluationPair", back_populates="evaluation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_lora_evaluations_model_created", "lora_model_id", "created_at"),
        Index("ix_lora_evaluations_status", "status"),
    )


class EvaluationPair(Base):
    """One original-vs-generated comparison within an evaluation."""

    __tablename__ = "evaluation_pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Link to evaluation
    evaluation_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("lora_evaluations.id", ondelete="CASCADE"), nullable=False
    )

    # Original image
    original_image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )

    # Prompt used for generation
    prompt_used: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Generated image info
    generated_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    generated_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_thumbnail_small: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_thumbnail_medium: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metric scores
    embedding_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    vision_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    vision_assessment: Mapped[str | None] = mapped_column(Text, nullable=True)
    clip_image_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    clip_text_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Combined score
    pair_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Pair type: "reference" (vs original) or "creative" (novel prompt, no original)
    pair_type: Mapped[str] = mapped_column(
        String(32), default="reference", server_default="reference", nullable=False
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(32), default="pending", nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Detailed metrics (vision sub-scores etc.)
    metrics_detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationships
    evaluation = relationship("LoraEvaluation", back_populates="pairs")
    original_image = relationship("Image", lazy="joined")

    __table_args__ = (
        Index("ix_evaluation_pairs_evaluation_id", "evaluation_id"),
    )
