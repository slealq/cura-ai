"""CostDecision model for pre-persisted billing decisions."""
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DecisionStatus(str, enum.Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    CHARGED = "charged"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CostDecision(Base):
    """Pre-persisted billing decision created before a provider call."""

    __tablename__ = "cost_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    trace_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    catalog_entry_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cost_catalog.id", ondelete="SET NULL"), nullable=True
    )
    catalog_match_tier: Mapped[str | None] = mapped_column(String(16), nullable=True)

    estimated_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_sparks: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    cost_per_input_token: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 12), nullable=True
    )
    cost_per_output_token: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 12), nullable=True
    )
    cost_per_call: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    platform_markup: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    billing_model: Mapped[str | None] = mapped_column(String(32), nullable=True)

    image_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    request_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    reserved_sparks: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(256), nullable=True, unique=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_cost_decisions_trace_id", "trace_id"),
        Index("ix_cost_decisions_user_created", "user_id", "created_at"),
        Index("ix_cost_decisions_job_id", "job_id"),
        Index("ix_cost_decisions_status", "status"),
        Index("ix_cost_decisions_image_id", "image_id"),
    )
