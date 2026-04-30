"""Cluster and ClusterMembership database models."""
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
    from app.models.image import Image


class ClusteringMethod(str, enum.Enum):
    """Method used for clustering."""

    HDBSCAN = "hdbscan"
    KMEANS = "kmeans"
    GRAPH = "graph"


class Cluster(Base):
    """Cluster model representing a group of similar design images."""

    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Clustering metadata
    method: Mapped[ClusteringMethod] = mapped_column(
        Enum(ClusteringMethod, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)

    # Cluster properties
    centroid_embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # AI-generated summaries
    summary_title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    summary_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    common_tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    # Representative images (IDs of images closest to centroid)
    representative_image_ids: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False)

    # Cover image for list views
    cover_image_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="SET NULL"), nullable=True, index=True
    )
    cover_thumbnail_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # User curation
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Model versioning
    summarization_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    cover_image: Mapped["Image | None"] = relationship("Image", foreign_keys=[cover_image_id])
    memberships: Mapped[list["ClusterMembership"]] = relationship(
        "ClusterMembership", back_populates="cluster", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_clusters_run_id_size", "run_id", "size"),
        Index("ix_clusters_pinned_archived", "is_pinned", "is_archived"),
    )


class ClusterMembership(Base):
    """Association between images and clusters with confidence scores."""

    __tablename__ = "cluster_memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )

    # Membership metadata
    score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    distance_to_centroid: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # User curation
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    cluster: Mapped["Cluster"] = relationship("Cluster", back_populates="memberships")
    image: Mapped["Image"] = relationship("Image", back_populates="cluster_memberships")

    __table_args__ = (
        Index("ix_cluster_memberships_cluster_score", "cluster_id", "score"),
        Index("ix_cluster_memberships_image", "image_id"),
    )
