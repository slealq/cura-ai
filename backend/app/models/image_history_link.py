"""Indexed library ancestry; stable object keys are also portable sync keys."""
from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ImageHistoryLink(Base):
    __tablename__ = "image_history_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    result_image_id: Mapped[int] = mapped_column(ForeignKey("images.id", ondelete="CASCADE"), index=True)
    source_image_id: Mapped[int | None] = mapped_column(ForeignKey("images.id", ondelete="SET NULL"), index=True)
    result_key: Mapped[str] = mapped_column(String(512))
    source_key: Mapped[str] = mapped_column(String(512))

    __table_args__ = (UniqueConstraint("result_key", "source_key"),)
