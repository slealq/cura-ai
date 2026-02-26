"""Vision analysis result model for persisting AI vision outputs."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VisionResult(Base):
    """Persisted result of a vision analysis (tag/describe/custom)."""

    __tablename__ = "vision_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Source references (exactly one should be set, or none for uploaded sources)
    source_image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="SET NULL"), nullable=True
    )
    source_generated_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("generated_images.id", ondelete="SET NULL"), nullable=True
    )
    source_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Analysis parameters
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Results
    result_tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing & cost
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    charged_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    charged_sparks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
