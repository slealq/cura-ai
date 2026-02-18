"""Billing and usage tracking models."""
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TransactionType(str, enum.Enum):
    CREDIT = "credit"
    DEBIT = "debit"
    ADJUSTMENT = "adjustment"


class CostCatalog(Base):
    """Global pricing catalog for provider operations."""

    __tablename__ = "cost_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    cost_per_input_token: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 12), nullable=True, default=0
    )
    cost_per_output_token: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 12), nullable=True, default=0
    )
    cost_per_call: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True, default=0
    )
    platform_markup: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("2.0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("provider", "model", "operation", name="uq_cost_catalog_provider_model_op"),
    )


class UsageRecord(Base):
    """Per-user usage tracking for billing."""

    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    pipeline_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    charged_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_usage_records_user_created", "user_id", "created_at"),
        Index("ix_usage_records_user_operation", "user_id", "operation"),
    )


class UserBalance(Base):
    """Cached credit balance per user."""

    __tablename__ = "user_balance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, default=Decimal("0")
    )
    currency: Mapped[str] = mapped_column(String(16), nullable=False, default="credits")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class BalanceTransaction(Base):
    """Append-only ledger of balance changes."""

    __tablename__ = "balance_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_balance_transactions_user_created", "user_id", "created_at"),
    )
