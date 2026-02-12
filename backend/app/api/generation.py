"""Generation API endpoints for LoRA training and image generation."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import get_db
from app.models import Job, JobType, JobStatus
from app.models.generated_image import GenerationStatus
from app.models.lora_model import LoraModelStatus
from app.services.generation_service import get_generation_service
from app.services.settings_service import get_settings_service

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/generation", tags=["generation"])


# --- Schemas ---


class TrainLoraRequest(BaseModel):
    """Request to start LoRA training from a folder or cluster."""

    name: str = Field(..., min_length=1, max_length=256)
    trigger_word: str = Field(..., min_length=1, max_length=128)
    folder_id: int | None = None
    cluster_id: int | None = None
    description: str | None = None
    steps: int | None = None
    is_style: bool | None = None
    base_model: str = "flux-dev"
    use_captions: bool = False
    caption_include_tags: bool = True
    caption_include_description: bool = True


class GenerateRequest(BaseModel):
    """Request to generate images."""

    prompt: str = Field(..., min_length=1)
    negative_prompt: str | None = None
    lora_model_id: int | None = None
    lora_scale: float = Field(1.0, ge=0.0, le=2.0)
    width: int = Field(1024, ge=256, le=2048)
    height: int = Field(1024, ge=256, le=2048)
    num_inference_steps: int = Field(28, ge=1, le=100)
    guidance_scale: float = Field(3.5, ge=0.0, le=20.0)
    seed: int | None = None
    num_images: int = Field(1, ge=1, le=8)


class LoraModelResponse(BaseModel):
    """Response for a LoRA model."""

    id: int
    name: str
    trigger_word: str
    description: str | None
    folder_id: int | None
    folder_name: str | None
    cluster_id: int | None
    cluster_name: str | None
    base_model: str
    training_provider: str
    training_config: dict | None
    status: str
    error_message: str | None
    lora_url: str | None
    training_images_count: int
    job_id: int | None
    created_at: str
    training_started_at: str | None
    training_completed_at: str | None
    updated_at: str

    model_config = {"from_attributes": True}


class GeneratedImageResponse(BaseModel):
    """Response for a generated image."""

    id: int
    prompt: str
    negative_prompt: str | None
    base_model: str
    generation_provider: str
    lora_model_id: int | None
    lora_model_name: str | None
    lora_scale: float | None
    generation_params: dict | None
    status: str
    error_message: str | None
    object_key: str | None
    width: int | None
    height: int | None
    file_size: int | None
    mime_type: str | None
    thumbnail_uri_small: str | None
    thumbnail_uri_medium: str | None
    job_id: int | None
    created_at: str
    completed_at: str | None

    model_config = {"from_attributes": True}


class LoraListResponse(BaseModel):
    items: list[LoraModelResponse]
    total: int
    skip: int
    limit: int


class GeneratedImageListResponse(BaseModel):
    items: list[GeneratedImageResponse]
    total: int
    skip: int
    limit: int


# --- Helpers ---


def _lora_to_response(lora) -> LoraModelResponse:
    return LoraModelResponse(
        id=lora.id,
        name=lora.name,
        trigger_word=lora.trigger_word,
        description=lora.description,
        folder_id=lora.folder_id,
        folder_name=lora.folder.name if lora.folder else None,
        cluster_id=lora.cluster_id,
        cluster_name=(lora.cluster.display_name or lora.cluster.summary_title or f"Cluster {lora.cluster.id}") if lora.cluster else None,
        base_model=lora.base_model,
        training_provider=lora.training_provider,
        training_config=lora.training_config,
        status=lora.status.value,
        error_message=lora.error_message,
        lora_url=lora.lora_url,
        training_images_count=lora.training_images_count,
        job_id=lora.job_id,
        created_at=lora.created_at.isoformat(),
        training_started_at=lora.training_started_at.isoformat() if lora.training_started_at else None,
        training_completed_at=lora.training_completed_at.isoformat() if lora.training_completed_at else None,
        updated_at=lora.updated_at.isoformat(),
    )


def _gen_to_response(gen) -> GeneratedImageResponse:
    return GeneratedImageResponse(
        id=gen.id,
        prompt=gen.prompt,
        negative_prompt=gen.negative_prompt,
        base_model=gen.base_model,
        generation_provider=gen.generation_provider,
        lora_model_id=gen.lora_model_id,
        lora_model_name=gen.lora_model.name if gen.lora_model else None,
        lora_scale=gen.lora_scale,
        generation_params=gen.generation_params,
        status=gen.status.value,
        error_message=gen.error_message,
        object_key=gen.object_key,
        width=gen.width,
        height=gen.height,
        file_size=gen.file_size,
        mime_type=gen.mime_type,
        thumbnail_uri_small=gen.thumbnail_uri_small,
        thumbnail_uri_medium=gen.thumbnail_uri_medium,
        job_id=gen.job_id,
        created_at=gen.created_at.isoformat(),
        completed_at=gen.completed_at.isoformat() if gen.completed_at else None,
    )


# --- LoRA Routes ---


@router.post("/lora/train", status_code=201)
async def train_lora(request: TrainLoraRequest, db: Session = Depends(get_db)):
    """Start LoRA training from a folder or cluster of images."""
    if not request.folder_id and not request.cluster_id:
        raise HTTPException(status_code=400, detail="Either folder_id or cluster_id is required")
    if request.folder_id and request.cluster_id:
        raise HTTPException(status_code=400, detail="Provide either folder_id or cluster_id, not both")

    image_count = 0
    job_params: dict = {"trigger_word": request.trigger_word}

    if request.folder_id:
        from app.models.folder import Folder, FolderImage

        folder = db.query(Folder).filter(Folder.id == request.folder_id).first()
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        image_count = db.query(FolderImage).filter(FolderImage.folder_id == request.folder_id).count()
        if image_count < 5:
            raise HTTPException(status_code=400, detail=f"Folder has {image_count} images, minimum 5 required")
        job_params["folder_id"] = request.folder_id

    elif request.cluster_id:
        from app.models.cluster import Cluster, ClusterMembership

        cluster = db.query(Cluster).filter(Cluster.id == request.cluster_id).first()
        if not cluster:
            raise HTTPException(status_code=404, detail="Cluster not found")

        image_count = (
            db.query(ClusterMembership)
            .filter(ClusterMembership.cluster_id == request.cluster_id, ClusterMembership.is_excluded == False)
            .count()
        )
        if image_count < 5:
            raise HTTPException(status_code=400, detail=f"Cluster has {image_count} images, minimum 5 required")
        job_params["cluster_id"] = request.cluster_id

    # Get training config from settings
    settings_service = get_settings_service(db)
    training_defaults = settings_service.get_training_config()

    steps = request.steps or training_defaults.get("steps", 1000)
    is_style = request.is_style if request.is_style is not None else training_defaults.get("is_style", False)

    # Create job
    try:
        job = Job(
            job_type=JobType.LORA_TRAIN,
            status=JobStatus.PENDING,
            total_items=1,
            parameters=job_params,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create LoRA training job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create LoRA training job: {e}")

    # Create LoRA model record
    gen_service = get_generation_service(db)
    lora = gen_service.create_lora_model(
        name=request.name,
        trigger_word=request.trigger_word,
        training_provider=settings.default_training_provider,
        folder_id=request.folder_id,
        cluster_id=request.cluster_id,
        base_model=request.base_model,
        description=request.description,
        training_config={
            "steps": steps,
            "is_style": is_style,
            "use_captions": request.use_captions,
            "caption_include_tags": request.caption_include_tags,
            "caption_include_description": request.caption_include_description,
        },
        training_images_count=image_count,
        job_id=job.id,
    )

    # Dispatch Celery task
    from app.workers.generation_tasks import train_lora as train_lora_task
    task = train_lora_task.delay(lora.id, job.id)

    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "training_started",
        "lora_model_id": lora.id,
        "job_id": job.id,
    }


@router.get("/lora", response_model=LoraListResponse)
async def list_lora_models(
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List LoRA models."""
    gen_service = get_generation_service(db)
    status_filter = LoraModelStatus(status) if status else None
    items = gen_service.get_lora_models(status=status_filter, skip=skip, limit=limit)
    total = gen_service.count_lora_models(status=status_filter)
    return LoraListResponse(
        items=[_lora_to_response(m) for m in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/lora/{lora_id}", response_model=LoraModelResponse)
async def get_lora_model(lora_id: int, db: Session = Depends(get_db)):
    """Get LoRA model detail."""
    gen_service = get_generation_service(db)
    lora = gen_service.get_lora_model(lora_id)
    if not lora:
        raise HTTPException(status_code=404, detail="LoRA model not found")
    return _lora_to_response(lora)


@router.delete("/lora/{lora_id}", status_code=204)
async def delete_lora_model(lora_id: int, db: Session = Depends(get_db)):
    """Delete a LoRA model."""
    gen_service = get_generation_service(db)
    if not gen_service.delete_lora_model(lora_id):
        raise HTTPException(status_code=404, detail="LoRA model not found")


# --- Generation Routes ---


@router.post("/generate", status_code=201)
async def generate_images(request: GenerateRequest, db: Session = Depends(get_db)):
    """Generate 1-8 images."""
    gen_service = get_generation_service(db)

    # Validate LoRA if specified
    if request.lora_model_id:
        lora = gen_service.get_lora_model(request.lora_model_id)
        if not lora:
            raise HTTPException(status_code=404, detail="LoRA model not found")
        if lora.status != LoraModelStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="LoRA model is not ready (not completed)")

    # Get generation defaults from settings
    settings_service = get_settings_service(db)
    gen_defaults = settings_service.get_generation_config()
    provider = settings.default_generation_provider

    # Create job
    try:
        job = Job(
            job_type=JobType.BATCH_GENERATE if request.num_images > 1 else JobType.GENERATE_IMAGE,
            status=JobStatus.PENDING,
            total_items=request.num_images,
            parameters={
                "prompt": request.prompt[:200],
                "num_images": request.num_images,
                "lora_model_id": request.lora_model_id,
            },
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create generation job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create generation job: {e}")

    # Create generated image records
    gen_ids = []
    for _ in range(request.num_images):
        gen = gen_service.create_generated_image(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            base_model=gen_defaults.get("base_model", "flux-dev"),
            generation_provider=provider,
            lora_model_id=request.lora_model_id,
            lora_scale=request.lora_scale,
            generation_params={
                "width": request.width,
                "height": request.height,
                "num_inference_steps": request.num_inference_steps,
                "guidance_scale": request.guidance_scale,
                "seed": request.seed,
            },
            job_id=job.id,
        )
        gen_ids.append(gen.id)

    # Dispatch Celery tasks
    from app.workers.generation_tasks import generate_image as gen_task, batch_generate

    if request.num_images == 1:
        task = gen_task.delay(gen_ids[0], job.id)
        job.celery_task_id = task.id
    else:
        task = batch_generate.delay(gen_ids, job.id)
        job.celery_task_id = task.id

    db.commit()

    return {
        "status": "generation_started",
        "job_id": job.id,
        "generated_image_ids": gen_ids,
    }


@router.get("/images", response_model=GeneratedImageListResponse)
async def list_generated_images(
    lora_model_id: int | None = None,
    status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List generated images."""
    gen_service = get_generation_service(db)
    status_filter = GenerationStatus(status) if status else None
    items = gen_service.get_generated_images(
        lora_model_id=lora_model_id,
        status=status_filter,
        skip=skip,
        limit=limit,
    )
    total = gen_service.count_generated_images(
        lora_model_id=lora_model_id,
        status=status_filter,
    )
    return GeneratedImageListResponse(
        items=[_gen_to_response(g) for g in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/images/{gen_id}", response_model=GeneratedImageResponse)
async def get_generated_image(gen_id: int, db: Session = Depends(get_db)):
    """Get generated image detail."""
    gen_service = get_generation_service(db)
    gen = gen_service.get_generated_image(gen_id)
    if not gen:
        raise HTTPException(status_code=404, detail="Generated image not found")
    return _gen_to_response(gen)


@router.get("/images/{gen_id}/file")
async def serve_generated_image(gen_id: int, db: Session = Depends(get_db)):
    """Serve generated image file."""
    gen_service = get_generation_service(db)
    gen = gen_service.get_generated_image(gen_id)
    if not gen or not gen.object_key:
        raise HTTPException(status_code=404, detail="Generated image file not found")

    storage_path = Path(settings.local_storage_path) / "generated" / gen.object_key
    if not storage_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        str(storage_path),
        media_type=gen.mime_type or "image/png",
        filename=gen.object_key,
    )


@router.get("/thumbnails/{filename}")
async def serve_generated_thumbnail(filename: str):
    """Serve generated image thumbnail."""
    storage_path = Path(settings.local_storage_path) / "generated_thumbnails" / filename
    if not storage_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return FileResponse(str(storage_path), media_type="image/jpeg")


@router.delete("/images/{gen_id}", status_code=204)
async def delete_generated_image(gen_id: int, db: Session = Depends(get_db)):
    """Delete a generated image."""
    gen_service = get_generation_service(db)
    if not gen_service.delete_generated_image(gen_id):
        raise HTTPException(status_code=404, detail="Generated image not found")
