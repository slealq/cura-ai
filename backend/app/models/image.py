"""Image and ImageMetadata database models."""
import enum
from datetime import datetime
from typing import TYPE_CHECKING

from pgvector.sqlalchemy import Vector
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.cluster import ClusterMembership


class ImageStatus(str, enum.Enum):
    """Status of image processing pipeline."""

    PENDING = "pending"
    INGESTED = "ingested"
    NORMALIZED = "normalized"
    TAGGED = "tagged"
    DESCRIBED = "described"
    EMBEDDED = "embedded"
    CLUSTERED = "clustered"
    FAILED = "failed"


STATUS_ORDER: dict[ImageStatus, int] = {
    ImageStatus.PENDING: 0,
    ImageStatus.INGESTED: 1,
    ImageStatus.NORMALIZED: 2,
    ImageStatus.TAGGED: 3,
    ImageStatus.DESCRIBED: 4,
    ImageStatus.EMBEDDED: 5,
    ImageStatus.CLUSTERED: 6,
}


class ImageSource(str, enum.Enum):
    """Source of the image."""

    UPLOAD = "upload"
    FOLDER_WATCHER = "folder_watcher"
    S3 = "s3"
    GCS = "gcs"
    GOOGLE_DRIVE = "google_drive"


class Image(Base):
    """Image model representing an ingested design image."""

    __tablename__ = "images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Source information
    source: Mapped[ImageSource] = mapped_column(Enum(ImageSource), nullable=False)
    original_uri: Mapped[str] = mapped_column(String(1024), nullable=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=True)

    # Deduplication
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    perceptual_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    # Image properties
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Thumbnails
    thumbnail_uri_small: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_uri_medium: Mapped[str | None] = mapped_column(String(512), nullable=True)
    thumbnail_uri_large: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Processing status
    status: Mapped[ImageStatus] = mapped_column(
        Enum(ImageStatus), default=ImageStatus.PENDING, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    ingested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    image_metadata: Mapped["ImageMetadata | None"] = relationship(
        "ImageMetadata", back_populates="image", uselist=False, cascade="all, delete-orphan"
    )
    cluster_memberships: Mapped[list["ClusterMembership"]] = relationship(
        "ClusterMembership", back_populates="image", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_images_status_created", "status", "created_at"),
        Index("ix_images_source_status", "source", "status"),
    )


class ImageMetadata(Base):
    """Metadata extracted from image via AI processing."""

    __tablename__ = "image_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # Flat categorization tags
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Color analysis
    dominant_colors: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)

    # AI-generated description
    description_long: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Embedding vector (1536 dimensions for OpenAI text-embedding-3-small)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    # Model versioning for reproducibility
    tagging_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    caption_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tagging_prompt_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationship
    image: Mapped["Image"] = relationship("Image", back_populates="image_metadata")

    __table_args__ = (
        Index(
            "ix_image_metadata_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
