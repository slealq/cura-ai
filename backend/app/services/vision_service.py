"""Service for managing vision analysis results."""
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.vision_result import VisionResult

logger = logging.getLogger(__name__)


class VisionService:
    """CRUD operations for VisionResult records."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id

    def create_result(
        self,
        mode: str,
        provider: str,
        model: str,
        prompt_text: str | None = None,
        result_tags: list[str] | None = None,
        result_text: str | None = None,
        duration_ms: int | None = None,
        source_image_id: int | None = None,
        source_generated_id: int | None = None,
        source_object_key: str | None = None,
    ) -> VisionResult:
        """Persist a vision analysis result."""
        result = VisionResult(
            user_id=self.user_id,
            mode=mode,
            provider=provider,
            model=model,
            prompt_text=prompt_text,
            result_tags=result_tags,
            result_text=result_text,
            duration_ms=duration_ms,
            source_image_id=source_image_id,
            source_generated_id=source_generated_id,
            source_object_key=source_object_key,
        )
        self.db.add(result)
        self.db.commit()
        self.db.refresh(result)
        return result

    def list_results(self, skip: int = 0, limit: int = 50) -> list[VisionResult]:
        """List results for this user, newest first."""
        return (
            self.db.query(VisionResult)
            .filter(VisionResult.user_id == self.user_id)
            .order_by(VisionResult.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_results(self) -> int:
        """Total result count for this user."""
        return (
            self.db.query(func.count(VisionResult.id))
            .filter(VisionResult.user_id == self.user_id)
            .scalar()
        )

    def get_result(self, result_id: int) -> VisionResult | None:
        """Get a single result by ID (user-scoped)."""
        return (
            self.db.query(VisionResult)
            .filter(VisionResult.id == result_id, VisionResult.user_id == self.user_id)
            .first()
        )

    def delete_result(self, result_id: int) -> bool:
        """Delete a result by ID. Returns True if deleted."""
        result = self.get_result(result_id)
        if not result:
            return False
        self.db.delete(result)
        self.db.commit()
        return True


def get_vision_service(db: Session, user_id: int) -> VisionService:
    """Factory for VisionService."""
    return VisionService(db, user_id)
