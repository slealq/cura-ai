"""Service for managing LoRA model evaluations."""
import logging
import uuid
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.models.lora_evaluation import EvaluationPair, EvaluationStatus, LoraEvaluation
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


class EvaluationService:
    """Service for LoRA evaluation CRUD operations."""

    def __init__(self, db: Session):
        self.db = db
        self.storage = get_storage_service()

    def create_evaluation(
        self,
        lora_model_id: int,
        sample_count: int,
        config: dict | None = None,
        job_id: int | None = None,
    ) -> LoraEvaluation:
        """Create a new evaluation record."""
        evaluation = LoraEvaluation(
            lora_model_id=lora_model_id,
            sample_count=sample_count,
            config=config,
            job_id=job_id,
            status=EvaluationStatus.PENDING,
        )
        self.db.add(evaluation)
        self.db.commit()
        self.db.refresh(evaluation)
        return evaluation

    def get_evaluation(self, eval_id: int) -> LoraEvaluation | None:
        """Get an evaluation by ID with pairs and lora_model."""
        return (
            self.db.query(LoraEvaluation)
            .options(
                joinedload(LoraEvaluation.pairs).joinedload(EvaluationPair.original_image),
                joinedload(LoraEvaluation.lora_model),
            )
            .filter(LoraEvaluation.id == eval_id)
            .first()
        )

    def get_evaluations_for_model(
        self, lora_model_id: int, skip: int = 0, limit: int = 50
    ) -> list[LoraEvaluation]:
        """Get evaluations for a model (without pairs for list view)."""
        return (
            self.db.query(LoraEvaluation)
            .options(joinedload(LoraEvaluation.lora_model))
            .filter(LoraEvaluation.lora_model_id == lora_model_id)
            .order_by(LoraEvaluation.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def count_evaluations(self, lora_model_id: int) -> int:
        """Count evaluations for a model."""
        return (
            self.db.query(LoraEvaluation)
            .filter(LoraEvaluation.lora_model_id == lora_model_id)
            .count()
        )

    def update_evaluation_status(
        self,
        eval_id: int,
        status: EvaluationStatus,
        error_message: str | None = None,
        overall_score: float | None = None,
        avg_embedding_similarity: float | None = None,
        avg_vision_score: float | None = None,
        assessment_summary: str | None = None,
        aggregate_results: dict | None = None,
    ) -> LoraEvaluation | None:
        """Update evaluation status and scores."""
        evaluation = self.db.query(LoraEvaluation).filter(LoraEvaluation.id == eval_id).first()
        if not evaluation:
            return None

        evaluation.status = status
        if error_message is not None:
            evaluation.error_message = error_message
        if overall_score is not None:
            evaluation.overall_score = overall_score
        if avg_embedding_similarity is not None:
            evaluation.avg_embedding_similarity = avg_embedding_similarity
        if avg_vision_score is not None:
            evaluation.avg_vision_score = avg_vision_score
        if assessment_summary is not None:
            evaluation.assessment_summary = assessment_summary
        if aggregate_results is not None:
            evaluation.aggregate_results = aggregate_results

        if status == EvaluationStatus.RUNNING:
            evaluation.started_at = datetime.utcnow()
        elif status in (EvaluationStatus.COMPLETED, EvaluationStatus.FAILED):
            evaluation.completed_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(evaluation)
        return evaluation

    def delete_evaluation(self, eval_id: int) -> bool:
        """Delete an evaluation and its pairs."""
        evaluation = self.db.query(LoraEvaluation).filter(LoraEvaluation.id == eval_id).first()
        if evaluation:
            self.db.delete(evaluation)
            self.db.commit()
            return True
        return False

    def create_pair(
        self,
        evaluation_id: int,
        original_image_id: int | None,
        prompt_used: str,
        pair_type: str = "reference",
    ) -> EvaluationPair:
        """Create a new evaluation pair."""
        pair = EvaluationPair(
            evaluation_id=evaluation_id,
            original_image_id=original_image_id,
            prompt_used=prompt_used,
            pair_type=pair_type,
            status="pending",
        )
        self.db.add(pair)
        self.db.commit()
        self.db.refresh(pair)
        return pair

    def update_pair_generated(
        self,
        pair_id: int,
        object_key: str,
        width: int,
        height: int,
        thumbnail_small: str | None = None,
        thumbnail_medium: str | None = None,
    ) -> EvaluationPair | None:
        """Update pair with generated image info."""
        pair = self.db.query(EvaluationPair).filter(EvaluationPair.id == pair_id).first()
        if not pair:
            return None

        pair.generated_object_key = object_key
        pair.generated_width = width
        pair.generated_height = height
        pair.generated_thumbnail_small = thumbnail_small
        pair.generated_thumbnail_medium = thumbnail_medium
        self.db.commit()
        self.db.refresh(pair)
        return pair

    def update_pair_scores(
        self,
        pair_id: int,
        embedding_similarity: float | None = None,
        vision_score: float | None = None,
        vision_assessment: str | None = None,
        clip_image_score: float | None = None,
        clip_text_score: float | None = None,
        pair_score: float | None = None,
        metrics_detail: dict | None = None,
    ) -> EvaluationPair | None:
        """Update pair with metric scores."""
        pair = self.db.query(EvaluationPair).filter(EvaluationPair.id == pair_id).first()
        if not pair:
            return None

        if embedding_similarity is not None:
            pair.embedding_similarity = embedding_similarity
        if vision_score is not None:
            pair.vision_score = vision_score
        if vision_assessment is not None:
            pair.vision_assessment = vision_assessment
        if clip_image_score is not None:
            pair.clip_image_score = clip_image_score
        if clip_text_score is not None:
            pair.clip_text_score = clip_text_score
        if pair_score is not None:
            pair.pair_score = pair_score
        if metrics_detail is not None:
            pair.metrics_detail = metrics_detail

        self.db.commit()
        self.db.refresh(pair)
        return pair

    def update_pair_status(
        self,
        pair_id: int,
        status: str,
        error_message: str | None = None,
    ) -> EvaluationPair | None:
        """Update pair status."""
        pair = self.db.query(EvaluationPair).filter(EvaluationPair.id == pair_id).first()
        if not pair:
            return None

        pair.status = status
        if error_message is not None:
            pair.error_message = error_message
        self.db.commit()
        self.db.refresh(pair)
        return pair

    async def save_eval_generated_image(
        self, image_data: bytes, object_key: str
    ) -> dict[str, str]:
        """Save evaluation-generated image to storage and create thumbnails.

        Returns dict with thumbnail paths.
        """
        await self.storage.save_generated_image(image_data, object_key, "image/png")
        thumbnails = await self.storage.generate_generated_thumbnails(image_data, object_key)
        return thumbnails


def get_evaluation_service(db: Session) -> EvaluationService:
    """Get evaluation service instance."""
    return EvaluationService(db)
