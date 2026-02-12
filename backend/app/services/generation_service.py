"""Service for managing LoRA models and generated images."""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.models.generated_image import GeneratedImage, GenerationStatus
from app.models.lora_model import LoraModel, LoraModelStatus
from app.services.storage import get_storage_service

logger = logging.getLogger(__name__)


class GenerationService:
    """Service for LoRA model and generated image CRUD operations."""

    def __init__(self, db: Session):
        self.db = db
        self.storage = get_storage_service()

    # --- LoRA Model CRUD ---

    def create_lora_model(
        self,
        name: str,
        trigger_word: str,
        training_provider: str,
        folder_id: int | None = None,
        cluster_id: int | None = None,
        base_model: str = "flux-dev",
        description: str | None = None,
        training_config: dict | None = None,
        training_images_count: int = 0,
        job_id: int | None = None,
    ) -> LoraModel:
        """Create a new LoRA model record."""
        lora = LoraModel(
            name=name,
            trigger_word=trigger_word,
            training_provider=training_provider,
            folder_id=folder_id,
            cluster_id=cluster_id,
            base_model=base_model,
            description=description,
            training_config=training_config,
            training_images_count=training_images_count,
            job_id=job_id,
            status=LoraModelStatus.PENDING,
        )
        self.db.add(lora)
        self.db.commit()
        self.db.refresh(lora)
        return lora

    def get_lora_model(self, lora_id: int) -> LoraModel | None:
        """Get a LoRA model by ID."""
        return (
            self.db.query(LoraModel)
            .options(joinedload(LoraModel.folder), joinedload(LoraModel.cluster))
            .filter(LoraModel.id == lora_id)
            .first()
        )

    def get_lora_models(
        self,
        status: LoraModelStatus | None = None,
        base_model: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[LoraModel]:
        """Get paginated list of LoRA models."""
        query = self.db.query(LoraModel).options(joinedload(LoraModel.folder), joinedload(LoraModel.cluster))
        if status:
            query = query.filter(LoraModel.status == status)
        if base_model:
            query = query.filter(LoraModel.base_model == base_model)
        return query.order_by(LoraModel.created_at.desc()).offset(skip).limit(limit).all()

    def count_lora_models(self, status: LoraModelStatus | None = None, base_model: str | None = None) -> int:
        """Count LoRA models with optional status filter."""
        query = self.db.query(LoraModel)
        if status:
            query = query.filter(LoraModel.status == status)
        if base_model:
            query = query.filter(LoraModel.base_model == base_model)
        return query.count()

    def update_lora_status(
        self,
        lora_id: int,
        status: LoraModelStatus,
        error_message: str | None = None,
        lora_url: str | None = None,
        provider_metadata: dict | None = None,
    ) -> LoraModel | None:
        """Update LoRA model status and related fields."""
        lora = self.db.query(LoraModel).filter(LoraModel.id == lora_id).first()
        if not lora:
            return None

        lora.status = status
        if error_message is not None:
            lora.error_message = error_message
        if lora_url is not None:
            lora.lora_url = lora_url
        if provider_metadata is not None:
            lora.provider_metadata = provider_metadata

        if status == LoraModelStatus.TRAINING:
            lora.training_started_at = datetime.utcnow()
        elif status in (LoraModelStatus.COMPLETED, LoraModelStatus.FAILED):
            lora.training_completed_at = datetime.utcnow()

        self.db.commit()
        self.db.refresh(lora)
        return lora

    def delete_lora_model(self, lora_id: int) -> bool:
        """Delete a LoRA model."""
        lora = self.db.query(LoraModel).filter(LoraModel.id == lora_id).first()
        if lora:
            self.db.delete(lora)
            self.db.commit()
            return True
        return False

    # --- Generated Image CRUD ---

    def create_generated_image(
        self,
        prompt: str,
        base_model: str,
        generation_provider: str,
        negative_prompt: str | None = None,
        lora_model_id: int | None = None,
        lora_scale: float | None = None,
        generation_params: dict | None = None,
        job_id: int | None = None,
    ) -> GeneratedImage:
        """Create a new generated image record."""
        gen = GeneratedImage(
            prompt=prompt,
            negative_prompt=negative_prompt,
            base_model=base_model,
            generation_provider=generation_provider,
            lora_model_id=lora_model_id,
            lora_scale=lora_scale,
            generation_params=generation_params,
            job_id=job_id,
            status=GenerationStatus.PENDING,
        )
        self.db.add(gen)
        self.db.commit()
        self.db.refresh(gen)
        return gen

    async def save_generated_result(
        self,
        generated_image_id: int,
        image_data: bytes,
        width: int,
        height: int,
        seed: int | None = None,
        provider_metadata: dict | None = None,
    ) -> GeneratedImage | None:
        """Save generated image data to storage and update record."""
        gen = self.db.query(GeneratedImage).filter(
            GeneratedImage.id == generated_image_id
        ).first()
        if not gen:
            return None

        # Generate object key
        object_key = f"{uuid.uuid4().hex}.png"

        # Save to storage
        await self.storage.save_generated_image(image_data, object_key, "image/png")

        # Generate thumbnails
        thumbnails = await self.storage.generate_generated_thumbnails(image_data, object_key)

        # Update record
        gen.object_key = object_key
        gen.width = width
        gen.height = height
        gen.file_size = len(image_data)
        gen.mime_type = "image/png"
        gen.thumbnail_uri_small = thumbnails.get("200")
        gen.thumbnail_uri_medium = thumbnails.get("400")
        gen.status = GenerationStatus.COMPLETED
        gen.completed_at = datetime.utcnow()
        if provider_metadata:
            gen.provider_metadata = provider_metadata
        if seed is not None:
            params = gen.generation_params or {}
            params["actual_seed"] = seed
            gen.generation_params = params

        self.db.commit()
        self.db.refresh(gen)
        return gen

    def get_generated_image(self, gen_id: int) -> GeneratedImage | None:
        """Get a generated image by ID."""
        return (
            self.db.query(GeneratedImage)
            .options(joinedload(GeneratedImage.lora_model))
            .filter(GeneratedImage.id == gen_id)
            .first()
        )

    def get_generated_images(
        self,
        lora_model_id: int | None = None,
        status: GenerationStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> list[GeneratedImage]:
        """Get paginated list of generated images."""
        query = self.db.query(GeneratedImage).options(
            joinedload(GeneratedImage.lora_model)
        )
        if lora_model_id is not None:
            query = query.filter(GeneratedImage.lora_model_id == lora_model_id)
        if status:
            query = query.filter(GeneratedImage.status == status)
        return query.order_by(GeneratedImage.created_at.desc()).offset(skip).limit(limit).all()

    def count_generated_images(
        self,
        lora_model_id: int | None = None,
        status: GenerationStatus | None = None,
    ) -> int:
        """Count generated images with optional filters."""
        query = self.db.query(GeneratedImage)
        if lora_model_id is not None:
            query = query.filter(GeneratedImage.lora_model_id == lora_model_id)
        if status:
            query = query.filter(GeneratedImage.status == status)
        return query.count()

    def delete_generated_image(self, gen_id: int) -> bool:
        """Delete a generated image record."""
        gen = self.db.query(GeneratedImage).filter(GeneratedImage.id == gen_id).first()
        if gen:
            self.db.delete(gen)
            self.db.commit()
            return True
        return False

    async def get_generated_image_data(self, gen_id: int) -> bytes | None:
        """Get raw generated image data."""
        gen = self.get_generated_image(gen_id)
        if not gen or not gen.object_key:
            return None
        return await self.storage.get_generated_image(gen.object_key)


def get_generation_service(db: Session) -> GenerationService:
    """Get generation service instance."""
    return GenerationService(db)
