"""Generation API endpoints for LoRA training, image generation, and evaluation."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_user, get_current_user_from_token_param
from app.db.base import get_db
from app.models import Job, JobStatus, JobType
from app.models.generated_image import GenerationStatus
from app.models.lora_evaluation import EvaluationStatus
from app.models.lora_model import LoraModelStatus
from app.models.user import User
from app.services.evaluation_service import get_evaluation_service
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
    learning_rate: float | None = None
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
    base_model: str | None = None
    width: int = Field(1024, ge=256, le=2048)
    height: int = Field(1024, ge=256, le=2048)
    num_inference_steps: int = Field(28, ge=1, le=100)
    guidance_scale: float = Field(3.5, ge=0.0, le=20.0)
    seed: int | None = None
    num_images: int = Field(1, ge=1, le=8)


class LoraPreviewImage(BaseModel):
    """A preview thumbnail for a LoRA model's source images."""

    id: int
    thumbnail_uri_small: str | None


class LatestEvaluationSummary(BaseModel):
    """Summary of the most recent evaluation for a LoRA model."""

    id: int
    status: str
    overall_score: float | None
    avg_embedding_similarity: float | None
    avg_vision_score: float | None
    completed_at: str | None


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
    source_preview_images: list[LoraPreviewImage] = Field(default_factory=list)
    latest_evaluation: LatestEvaluationSummary | None = None
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


def _get_source_preview_images(lora, db: Session) -> list[LoraPreviewImage]:
    """Get up to 4 preview thumbnails from the LoRA's source folder or cluster."""
    from app.models.image import Image

    if lora.folder_id and lora.folder:
        from app.models.folder import FolderImage

        images = (
            db.query(Image)
            .join(FolderImage, FolderImage.image_id == Image.id)
            .filter(FolderImage.folder_id == lora.folder_id)
            .order_by(Image.id)
            .limit(4)
            .all()
        )
        return [LoraPreviewImage(id=img.id, thumbnail_uri_small=img.thumbnail_uri_small) for img in images]

    if lora.cluster_id and lora.cluster:
        rep_ids = (lora.cluster.representative_image_ids or [])[:4]
        if rep_ids:
            images = db.query(Image).filter(Image.id.in_(rep_ids)).all()
            id_order = {img_id: i for i, img_id in enumerate(rep_ids)}
            images.sort(key=lambda img: id_order.get(img.id, 999))
            return [LoraPreviewImage(id=img.id, thumbnail_uri_small=img.thumbnail_uri_small) for img in images]

    return []


def _get_latest_evaluation(lora, db: Session) -> LatestEvaluationSummary | None:
    """Get the most recent evaluation for a LoRA model."""
    from app.models.lora_evaluation import LoraEvaluation
    eval_row = (
        db.query(LoraEvaluation)
        .filter(LoraEvaluation.lora_model_id == lora.id)
        .order_by(LoraEvaluation.created_at.desc())
        .first()
    )
    if not eval_row:
        return None
    return LatestEvaluationSummary(
        id=eval_row.id,
        status=eval_row.status.value if hasattr(eval_row.status, 'value') else eval_row.status,
        overall_score=eval_row.overall_score,
        avg_embedding_similarity=eval_row.avg_embedding_similarity,
        avg_vision_score=eval_row.avg_vision_score,
        completed_at=eval_row.completed_at.isoformat() if eval_row.completed_at else None,
    )


def _lora_to_response(lora, db: Session) -> LoraModelResponse:
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
        source_preview_images=_get_source_preview_images(lora, db),
        latest_evaluation=_get_latest_evaluation(lora, db),
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
async def train_lora(request: TrainLoraRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
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
            .filter(ClusterMembership.cluster_id == request.cluster_id, ClusterMembership.is_excluded.is_(False))
            .count()
        )
        if image_count < 5:
            raise HTTPException(status_code=400, detail=f"Cluster has {image_count} images, minimum 5 required")
        job_params["cluster_id"] = request.cluster_id

    # Get training config from settings
    settings_service = get_settings_service(db, current_user.id)
    training_defaults = settings_service.get_training_config(request.base_model)

    # Use model-aware default steps
    from app.providers.fal_provider import FAL_MODEL_CONFIG
    model_config = FAL_MODEL_CONFIG.get(request.base_model, FAL_MODEL_CONFIG["flux-dev"])
    steps = request.steps or training_defaults.get("steps", model_config["default_steps"])
    is_style = request.is_style if request.is_style is not None else training_defaults.get("is_style", False)

    # Create job
    try:
        job = Job(
            job_type=JobType.LORA_TRAIN,
            status=JobStatus.PENDING,
            total_items=1,
            parameters=job_params,
            user_id=current_user.id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create LoRA training job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create LoRA training job: {e}")

    # Create LoRA model record
    gen_service = get_generation_service(db, current_user.id)
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
            **({"learning_rate": request.learning_rate} if request.learning_rate is not None else {}),
        },
        training_images_count=image_count,
        job_id=job.id,
    )

    # Store lora_model_id in job parameters for frontend recovery buttons
    job.parameters = {**job.parameters, "lora_model_id": lora.id}

    # Dispatch Celery task
    from app.workers.generation_tasks import train_lora as train_lora_task
    task = train_lora_task.delay(lora.id, job.id, current_user.id)

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
    base_model: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List LoRA models."""
    gen_service = get_generation_service(db, current_user.id)
    status_filter = LoraModelStatus(status) if status else None
    items = gen_service.get_lora_models(status=status_filter, base_model=base_model, skip=skip, limit=limit)
    total = gen_service.count_lora_models(status=status_filter, base_model=base_model)
    return LoraListResponse(
        items=[_lora_to_response(m, db) for m in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/lora/{lora_id}", response_model=LoraModelResponse)
async def get_lora_model(lora_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get LoRA model detail."""
    gen_service = get_generation_service(db, current_user.id)
    lora = gen_service.get_lora_model(lora_id)
    if not lora:
        raise HTTPException(status_code=404, detail="LoRA model not found")
    return _lora_to_response(lora, db)


@router.post("/lora/{lora_id}/recover")
async def recover_lora_training(lora_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Recover a stuck LoRA training job.

    For TRAINING models with a request_id: checks fal.ai status.
    If completed, fetches result and finalizes. If still running, re-dispatches polling.
    """
    gen_service = get_generation_service(db, current_user.id)
    lora = gen_service.get_lora_model(lora_id)
    if not lora:
        raise HTTPException(status_code=404, detail="LoRA model not found")

    if lora.status != LoraModelStatus.TRAINING:
        raise HTTPException(status_code=400, detail=f"LoRA model is not in TRAINING status (current: {lora.status.value})")

    request_id = (lora.provider_metadata or {}).get("request_id")
    if not request_id:
        raise HTTPException(status_code=400, detail="No request_id found — cannot recover. Training may not have been submitted.")

    # Check fal.ai status
    from app.providers import get_trainer
    trainer = get_trainer(lora.training_provider, db=db, base_model=lora.base_model)

    try:
        status_info = await trainer.check_training_status(request_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to check fal.ai status: {e}")

    status_type = status_info.get("status", "")

    if status_type == "Completed":
        # Fetch result and finalize
        try:
            result = await trainer.get_training_result(request_id)
            gen_service.update_lora_status(
                lora_id,
                LoraModelStatus.COMPLETED,
                lora_url=result.lora_url,
                provider_metadata={"request_id": request_id, **(result.metadata or {})},
            )
            # Update job if exists
            if lora.job_id:
                job = db.query(Job).filter(Job.id == lora.job_id).first()
                if job:
                    job.status = JobStatus.COMPLETED
                    from datetime import datetime
                    job.completed_at = datetime.utcnow()
                    job.progress = 1
                    job.result = {"lora_url": result.lora_url, "request_id": request_id, "recovered": True}
                    db.commit()
            return {"status": "recovered", "lora_url": result.lora_url, "request_id": request_id}
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Training completed but failed to fetch result: {e}")

    elif "error" in status_type.lower() or status_info.get("error"):
        error_msg = status_info.get("error", f"Training failed with status: {status_type}")
        gen_service.update_lora_status(lora_id, LoraModelStatus.FAILED, error_msg)
        if lora.job_id:
            job = db.query(Job).filter(Job.id == lora.job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = error_msg
                db.commit()
        return {"status": "failed", "error": error_msg}

    else:
        # Still running — re-dispatch celery task to resume polling
        from app.workers.generation_tasks import train_lora as train_lora_task
        task = train_lora_task.delay(lora_id, lora.job_id, current_user.id)
        if lora.job_id:
            job = db.query(Job).filter(Job.id == lora.job_id).first()
            if job:
                job.celery_task_id = task.id
                job.status = JobStatus.RUNNING
                db.commit()
        return {"status": "polling_resumed", "fal_status": status_type, "request_id": request_id}


@router.post("/lora/{lora_id}/retry")
async def retry_lora_training(lora_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Retry a FAILED LoRA training job from scratch."""
    gen_service = get_generation_service(db, current_user.id)
    lora = gen_service.get_lora_model(lora_id)
    if not lora:
        raise HTTPException(status_code=404, detail="LoRA model not found")

    if lora.status != LoraModelStatus.FAILED:
        raise HTTPException(status_code=400, detail=f"Can only retry FAILED models (current: {lora.status.value})")

    # Create a new job
    try:
        job = Job(
            job_type=JobType.LORA_TRAIN,
            status=JobStatus.PENDING,
            total_items=1,
            parameters={"trigger_word": lora.trigger_word, "retry_of_lora_id": lora_id},
            user_id=current_user.id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create retry job: {e}")

    # Reset LoRA to PENDING
    gen_service.update_lora_status(lora_id, LoraModelStatus.PENDING)
    lora.job_id = job.id
    lora.error_message = None
    lora.provider_metadata = None
    db.commit()

    # Dispatch
    from app.workers.generation_tasks import train_lora as train_lora_task
    task = train_lora_task.delay(lora_id, job.id, current_user.id)

    job.celery_task_id = task.id
    db.commit()

    return {"status": "retry_started", "lora_model_id": lora_id, "job_id": job.id}


@router.delete("/lora/{lora_id}", status_code=204)
async def delete_lora_model(lora_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a LoRA model."""
    gen_service = get_generation_service(db, current_user.id)
    if not gen_service.delete_lora_model(lora_id):
        raise HTTPException(status_code=404, detail="LoRA model not found")


# --- Generation Routes ---


@router.post("/generate", status_code=201)
async def generate_images(request: GenerateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Generate 1-8 images."""
    gen_service = get_generation_service(db, current_user.id)

    # Determine effective base_model
    effective_base_model = request.base_model or "flux-dev"

    # Validate LoRA if specified
    if request.lora_model_id:
        lora = gen_service.get_lora_model(request.lora_model_id)
        if not lora:
            raise HTTPException(status_code=404, detail="LoRA model not found")
        if lora.status != LoraModelStatus.COMPLETED:
            raise HTTPException(status_code=400, detail="LoRA model is not ready (not completed)")
        # Infer base_model from LoRA if not explicitly set
        if not request.base_model:
            effective_base_model = lora.base_model
        elif lora.base_model != effective_base_model:
            raise HTTPException(
                status_code=400,
                detail=f"LoRA model is trained on '{lora.base_model}' but generation requested '{effective_base_model}'. They must match.",
            )

    # Get generation defaults from settings
    settings_service = get_settings_service(db, current_user.id)
    settings_service.get_generation_config()
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
            user_id=current_user.id,
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
            base_model=effective_base_model,
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
    from app.workers.generation_tasks import batch_generate
    from app.workers.generation_tasks import generate_image as gen_task

    if request.num_images == 1:
        task = gen_task.delay(gen_ids[0], job.id, current_user.id)
        job.celery_task_id = task.id
    else:
        task = batch_generate.delay(gen_ids, job.id, current_user.id)
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
    current_user: User = Depends(get_current_user),
):
    """List generated images."""
    gen_service = get_generation_service(db, current_user.id)
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
async def get_generated_image(gen_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get generated image detail."""
    gen_service = get_generation_service(db, current_user.id)
    gen = gen_service.get_generated_image(gen_id)
    if not gen:
        raise HTTPException(status_code=404, detail="Generated image not found")
    return _gen_to_response(gen)


@router.get("/images/{gen_id}/file")
async def serve_generated_image(gen_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_from_token_param)):
    """Serve generated image file."""
    from app.services.storage import get_storage_service

    gen_service = get_generation_service(db, current_user.id)
    gen = gen_service.get_generated_image(gen_id)
    if not gen or not gen.object_key:
        raise HTTPException(status_code=404, detail="Generated image file not found")

    storage = get_storage_service()
    response = storage.get_file_response_with_filename(
        "generated", gen.object_key, gen.mime_type or "image/png",
        download_filename=gen.object_key,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="File not found")
    return response


@router.get("/thumbnails/{filename}")
async def serve_generated_thumbnail(filename: str, current_user: User = Depends(get_current_user_from_token_param)):
    """Serve generated image thumbnail."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    response = storage.get_file_response("generated_thumbnails", filename, "image/jpeg")
    if response is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return response


@router.delete("/images/{gen_id}", status_code=204)
async def delete_generated_image(gen_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a generated image."""
    gen_service = get_generation_service(db, current_user.id)
    if not gen_service.delete_generated_image(gen_id):
        raise HTTPException(status_code=404, detail="Generated image not found")


# --- Evaluation Schemas ---


class StartEvaluationRequest(BaseModel):
    """Request to start a LoRA model evaluation."""

    sample_count: int = Field(5, ge=1, le=50)
    creative_count: int = Field(0, ge=0, le=20)
    metrics_enabled: list[str] = Field(default=["embedding_similarity"])
    generation_params: dict | None = None
    vision_eval_provider: str | None = None


class EvaluationPairResponse(BaseModel):
    """Response for a single evaluation pair."""

    id: int
    pair_type: str
    original_image_id: int | None
    original_thumbnail: str | None
    original_object_key: str | None
    prompt_used: str | None
    generated_object_key: str | None
    generated_thumbnail_small: str | None
    generated_thumbnail_medium: str | None
    generated_width: int | None
    generated_height: int | None
    embedding_similarity: float | None
    vision_score: float | None
    vision_assessment: str | None
    clip_image_score: float | None
    clip_text_score: float | None
    pair_score: float | None
    metrics_detail: dict | None
    status: str
    error_message: str | None

    model_config = {"from_attributes": True}


class EvaluationResponse(BaseModel):
    """Response for a full evaluation with pairs."""

    id: int
    lora_model_id: int
    lora_model_name: str | None
    sample_count: int
    config: dict | None
    status: str
    error_message: str | None
    overall_score: float | None
    avg_embedding_similarity: float | None
    avg_vision_score: float | None
    assessment_summary: str | None
    aggregate_results: dict | None
    training_config: dict | None
    training_images_count: int
    job_id: int | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    pairs: list[EvaluationPairResponse]

    model_config = {"from_attributes": True}


class EvaluationListItem(BaseModel):
    """Evaluation list item (without pairs)."""

    id: int
    lora_model_id: int
    sample_count: int
    status: str
    overall_score: float | None
    avg_embedding_similarity: float | None
    avg_vision_score: float | None
    job_id: int | None
    created_at: str
    completed_at: str | None

    model_config = {"from_attributes": True}


class EvaluationListResponse(BaseModel):
    items: list[EvaluationListItem]
    total: int
    skip: int
    limit: int


# --- Evaluation Helpers ---


def _pair_to_response(pair) -> EvaluationPairResponse:
    original_thumb = None
    original_object_key = None
    if pair.original_image:
        if pair.original_image.thumbnail_uri_small:
            original_thumb = pair.original_image.thumbnail_uri_small
        original_object_key = pair.original_image.object_key

    return EvaluationPairResponse(
        id=pair.id,
        pair_type=getattr(pair, "pair_type", "reference"),
        original_image_id=pair.original_image_id,
        original_thumbnail=original_thumb,
        original_object_key=original_object_key,
        prompt_used=pair.prompt_used,
        generated_object_key=pair.generated_object_key,
        generated_thumbnail_small=pair.generated_thumbnail_small,
        generated_thumbnail_medium=pair.generated_thumbnail_medium,
        generated_width=pair.generated_width,
        generated_height=pair.generated_height,
        embedding_similarity=pair.embedding_similarity,
        vision_score=pair.vision_score,
        vision_assessment=pair.vision_assessment,
        clip_image_score=pair.clip_image_score,
        clip_text_score=pair.clip_text_score,
        pair_score=pair.pair_score,
        metrics_detail=pair.metrics_detail,
        status=pair.status,
        error_message=pair.error_message,
    )


def _eval_to_response(evaluation) -> EvaluationResponse:
    lora = evaluation.lora_model
    return EvaluationResponse(
        id=evaluation.id,
        lora_model_id=evaluation.lora_model_id,
        lora_model_name=lora.name if lora else None,
        sample_count=evaluation.sample_count,
        config=evaluation.config,
        status=evaluation.status.value if isinstance(evaluation.status, EvaluationStatus) else evaluation.status,
        error_message=evaluation.error_message,
        overall_score=evaluation.overall_score,
        avg_embedding_similarity=evaluation.avg_embedding_similarity,
        avg_vision_score=evaluation.avg_vision_score,
        assessment_summary=evaluation.assessment_summary,
        aggregate_results=evaluation.aggregate_results,
        training_config=lora.training_config if lora else None,
        training_images_count=lora.training_images_count if lora else 0,
        job_id=evaluation.job_id,
        created_at=evaluation.created_at.isoformat(),
        started_at=evaluation.started_at.isoformat() if evaluation.started_at else None,
        completed_at=evaluation.completed_at.isoformat() if evaluation.completed_at else None,
        pairs=[_pair_to_response(p) for p in (evaluation.pairs or [])],
    )


def _eval_to_list_item(evaluation) -> EvaluationListItem:
    return EvaluationListItem(
        id=evaluation.id,
        lora_model_id=evaluation.lora_model_id,
        sample_count=evaluation.sample_count,
        status=evaluation.status.value if isinstance(evaluation.status, EvaluationStatus) else evaluation.status,
        overall_score=evaluation.overall_score,
        avg_embedding_similarity=evaluation.avg_embedding_similarity,
        avg_vision_score=evaluation.avg_vision_score,
        job_id=evaluation.job_id,
        created_at=evaluation.created_at.isoformat(),
        completed_at=evaluation.completed_at.isoformat() if evaluation.completed_at else None,
    )


# --- Evaluation Routes ---


@router.post("/lora/{lora_id}/evaluate", status_code=201)
async def start_evaluation(lora_id: int, request: StartEvaluationRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Start an evaluation for a LoRA model."""
    gen_service = get_generation_service(db, current_user.id)
    lora = gen_service.get_lora_model(lora_id)
    if not lora:
        raise HTTPException(status_code=404, detail="LoRA model not found")
    if lora.status != LoraModelStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="LoRA model is not completed")
    if not lora.lora_url:
        raise HTTPException(status_code=400, detail="LoRA model has no trained weights URL")

    # Create job
    try:
        job = Job(
            job_type=JobType.LORA_EVALUATE,
            status=JobStatus.PENDING,
            total_items=request.sample_count,
            parameters={
                "lora_model_id": lora_id,
                "sample_count": request.sample_count,
                "metrics": request.metrics_enabled,
            },
            user_id=current_user.id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create evaluation job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create evaluation job: {e}")

    # Create evaluation record
    eval_service = get_evaluation_service(db, current_user.id)
    evaluation = eval_service.create_evaluation(
        lora_model_id=lora_id,
        sample_count=request.sample_count,
        config={
            "metrics_enabled": request.metrics_enabled,
            "generation_params": request.generation_params or {},
            "vision_eval_provider": request.vision_eval_provider,
            "creative_count": request.creative_count,
        },
        job_id=job.id,
    )

    # Dispatch Celery task
    from app.workers.generation_tasks import evaluate_lora as evaluate_task
    task = evaluate_task.delay(evaluation.id, job.id, current_user.id)

    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "evaluation_started",
        "evaluation_id": evaluation.id,
        "job_id": job.id,
    }


@router.get("/lora/{lora_id}/evaluations", response_model=EvaluationListResponse)
async def list_evaluations(
    lora_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List evaluations for a LoRA model."""
    eval_service = get_evaluation_service(db, current_user.id)
    items = eval_service.get_evaluations_for_model(lora_id, skip=skip, limit=limit)
    total = eval_service.count_evaluations(lora_id)
    return EvaluationListResponse(
        items=[_eval_to_list_item(e) for e in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/evaluations/{eval_id}", response_model=EvaluationResponse)
async def get_evaluation(eval_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get evaluation detail with all pairs."""
    eval_service = get_evaluation_service(db, current_user.id)
    evaluation = eval_service.get_evaluation(eval_id)
    if not evaluation:
        raise HTTPException(status_code=404, detail="Evaluation not found")
    return _eval_to_response(evaluation)


@router.delete("/evaluations/{eval_id}", status_code=204)
async def delete_evaluation(eval_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete an evaluation and its pairs."""
    eval_service = get_evaluation_service(db, current_user.id)
    if not eval_service.delete_evaluation(eval_id):
        raise HTTPException(status_code=404, detail="Evaluation not found")


@router.get("/evaluations/{eval_id}/pairs/{pair_id}/generated-file")
async def serve_eval_generated_image(eval_id: int, pair_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_from_token_param)):
    """Serve generated image file from an evaluation pair."""
    from app.models.lora_evaluation import EvaluationPair
    from app.services.storage import get_storage_service

    pair = db.query(EvaluationPair).filter(
        EvaluationPair.id == pair_id,
        EvaluationPair.evaluation_id == eval_id,
    ).first()
    if not pair or not pair.generated_object_key:
        raise HTTPException(status_code=404, detail="Generated image not found")

    storage = get_storage_service()
    response = storage.get_file_response_with_filename(
        "generated", pair.generated_object_key, "image/png",
        download_filename=pair.generated_object_key,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="File not found")
    return response
