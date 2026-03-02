"""API key model for storing encrypted provider credentials."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class APIProvider(str, enum.Enum):
    """Supported API providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    FAL = "fal"
    SENTRY = "sentry"


class APIKeyStatus(str, enum.Enum):
    """Status of an API key."""
    ACTIVE = "active"
    INVALID = "invalid"
    QUOTA_EXCEEDED = "quota_exceeded"
    UNKNOWN = "unknown"


class APIKey(Base):
    """Model for storing encrypted API keys."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)

    # Encrypted key value (using Fernet symmetric encryption)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)

    # Key metadata (last 4 chars for display, e.g., "...a1b2")
    key_suffix: Mapped[str] = mapped_column(String(8), nullable=False)

    # Validation status
    status: Mapped[str] = mapped_column(String(32), default="unknown", nullable=False)
    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_api_keys_provider_status", "provider", "status"),
    )
