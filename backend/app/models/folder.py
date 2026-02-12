"""Folder and FolderImage database models."""
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Folder(Base):
    """Folder model for organizing images into collections."""

    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    folder_images: Mapped[list["FolderImage"]] = relationship(
        "FolderImage", back_populates="folder", cascade="all, delete-orphan"
    )


class FolderImage(Base):
    """Association between folders and images."""

    __tablename__ = "folder_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    folder_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("folders.id", ondelete="CASCADE"), nullable=False
    )
    image_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False
    )
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    folder: Mapped["Folder"] = relationship("Folder", back_populates="folder_images")
    image = relationship("Image", back_populates="folder_images")

    __table_args__ = (
        UniqueConstraint("folder_id", "image_id", name="uq_folder_image"),
        Index("ix_folder_images_folder_id", "folder_id"),
        Index("ix_folder_images_image_id", "image_id"),
    )
