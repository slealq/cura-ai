"""Edit API endpoints for AI-powered image editing."""
import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_current_user_from_token_param
from app.db.base import get_db
from app.models import Job, JobStatus, JobType
from app.models.user import User
from app.services.generation_service import get_generation_service
from app.workers.dispatch import dispatch_or_fail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/edit", tags=["edit"])

SUPPORTED_EDIT_MODELS = {
    "nano-banana-pro-edit",
    "kling-image",
    "grok-imagine",
    "seedream-5-pro-edit",
    "qwen-image-2-pro-edit",
    "flux-2-lora-edit",
}

# --- Schemas ---


class EditImageRequest(BaseModel):
    """Request to edit images."""

    prompt: str = Field("", max_length=8000)
    negative_prompt: str | None = Field(None, max_length=500)
    source_image_ids: list[int] | None = None
    source_generated_ids: list[int] | None = None
    source_upload_keys: list[str] | None = None
    edit_model: str = "nano-banana-pro-edit"
    image_size: dict | str | None = None
    num_images: int = Field(1, ge=1, le=9)
    seed: int | None = Field(None, ge=0, le=2147483647)
    output_format: str = "png"
    enable_prompt_expansion: bool = True
    enable_safety_checker: bool = True
    # Kling-specific fields
    resolution: str | None = None  # 1K, 2K, 4K
    aspect_ratio: str | None = None  # 16:9, 9:16, 1:1, 4:3, 3:4, 3:2, 2:3, 21:9, auto
    # Nano Banana Pro fields
    safety_tolerance: str | None = None
    enable_web_search: bool | None = None
    # Face swap fields
    enable_occlusion_prevention: bool = False


class EditImageResponse(BaseModel):
    """Response after submitting an edit request."""

    status: str
    job_id: int
    generated_image_ids: list[int]


class EditSourceUploadResponse(BaseModel):
    """Response after uploading a source image for editing."""

    object_key: str


class BulkDeleteImagesRequest(BaseModel):
    """Request to delete multiple edited images."""

    image_ids: list[int]


# --- Helpers ---


def _gen_to_response(gen, db: Session) -> dict:
    """Convert GeneratedImage to response dict (reuses generation pattern)."""
    from app.api.generation import _gen_to_response as gen_response
    return gen_response(gen, db).model_dump()


# --- Endpoints ---


@router.post("", response_model=EditImageResponse)
async def edit_images(
    request: EditImageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit an image edit request. Creates job + generated image records."""
    from app.providers.fal_provider import FAL_EDIT_MODEL_CONFIG

    # Validate edit model
    if request.edit_model not in SUPPORTED_EDIT_MODELS:
        raise HTTPException(status_code=400, detail=f"Unknown edit model: {request.edit_model}")

    model_config = FAL_EDIT_MODEL_CONFIG[request.edit_model]

    is_face_swap = model_config.get("uses_face_swap", False)

    # Require prompt for non-face-swap models
    if not is_face_swap and not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required for this model")

    # Default prompt for face-swap display
    if is_face_swap and not request.prompt.strip():
        request.prompt = "Face swap"

    # Collect and validate source images
    source_count = 0
    source_refs: dict = {}

    if request.source_image_ids:
        source_count += len(request.source_image_ids)
        source_refs["image_ids"] = request.source_image_ids

    if request.source_generated_ids:
        source_count += len(request.source_generated_ids)
        source_refs["generated_ids"] = request.source_generated_ids

    if request.source_upload_keys:
        source_count += len(request.source_upload_keys)
        source_refs["upload_keys"] = request.source_upload_keys

    if source_count == 0:
        raise HTTPException(status_code=400, detail="At least one source image is required")

    max_sources = model_config.get("max_source_images", 3)
    if source_count > max_sources:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {max_sources} source images allowed for {request.edit_model}",
        )

    if is_face_swap and source_count != 2:
        raise HTTPException(
            status_code=400,
            detail="Face swap requires exactly 2 images: source face and target image",
        )

    # Validate gallery image IDs exist
    if request.source_image_ids:
        from app.services.image_service import get_image_service
        img_service = get_image_service(db, current_user.id)
        for img_id in request.source_image_ids:
            img = img_service.get_image(img_id)
            if not img:
                raise HTTPException(status_code=404, detail=f"Image {img_id} not found")

    # Validate generated image IDs exist
    gen_service = get_generation_service(db, current_user.id)
    if request.source_generated_ids:
        for gen_id in request.source_generated_ids:
            gen = gen_service.get_generated_image(gen_id)
            if not gen:
                raise HTTPException(status_code=404, detail=f"Generated image {gen_id} not found")

    # Build generation_params
    gen_params: dict = {
        "mode": "edit",
        "edit_model": request.edit_model,
        "sources": source_refs,
        "output_format": request.output_format,
        "enable_prompt_expansion": request.enable_prompt_expansion,
        "enable_safety_checker": request.enable_safety_checker,
    }
    if request.image_size is not None:
        gen_params["image_size"] = request.image_size
    if request.seed is not None:
        gen_params["seed"] = request.seed
    if request.resolution is not None:
        gen_params["resolution"] = request.resolution
    if request.aspect_ratio is not None:
        gen_params["aspect_ratio"] = request.aspect_ratio
    if request.safety_tolerance is not None:
        gen_params["safety_tolerance"] = request.safety_tolerance
    if request.enable_web_search is not None:
        gen_params["enable_web_search"] = request.enable_web_search
    if request.enable_occlusion_prevention:
        gen_params["enable_occlusion_prevention"] = True

    # Create job
    try:
        job = Job(
            job_type=JobType.BATCH_EDIT if request.num_images > 1 else JobType.EDIT_IMAGE,
            status=JobStatus.PENDING,
            total_items=request.num_images,
            parameters={
                "prompt": request.prompt[:200],
                "num_images": request.num_images,
                "edit_model": request.edit_model,
            },
            user_id=current_user.id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create edit job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create edit job: {e}")

    # Create generated image records (one per num_images)
    generated_images = []
    gen_ids = []
    for _ in range(request.num_images):
        gen = gen_service.create_generated_image(
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            base_model=request.edit_model,
            generation_provider="fal",
            generation_params=gen_params,
            job_id=job.id,
        )
        generated_images.append(gen)
        gen_ids.append(gen.id)

    # Dispatch Celery tasks
    from app.workers.generation_tasks import batch_edit
    from app.workers.generation_tasks import edit_image as edit_task

    if request.num_images == 1:
        task = dispatch_or_fail(
            edit_task, job, db, gen_ids[0], job.id, current_user.id, generated_images=generated_images
        )
        job.celery_task_id = task.id
    else:
        task = dispatch_or_fail(
            batch_edit, job, db, gen_ids, job.id, current_user.id, generated_images=generated_images
        )
        job.celery_task_id = task.id

    db.commit()

    return EditImageResponse(
        status="edit_started",
        job_id=job.id,
        generated_image_ids=gen_ids,
    )


@router.post("/upload-source", response_model=EditSourceUploadResponse)
async def upload_source_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a source image for editing. Returns an object_key for use in edit requests."""
    # Validate file type
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}")

    # Read and validate size
    data = await file.read()
    max_size = 30 * 1024 * 1024  # 30MB
    if len(data) > max_size:
        raise HTTPException(status_code=400, detail="File too large (max 30MB)")

    # Generate object key and save
    ext = file.content_type.split("/")[-1] if file.content_type else "png"
    if ext == "jpeg":
        ext = "jpg"
    object_key = f"edit-sources/{uuid.uuid4().hex}.{ext}"

    from app.services.storage import get_storage_service
    storage = get_storage_service()
    await storage.save_generated_image(data, object_key, file.content_type or "image/png")

    return EditSourceUploadResponse(object_key=object_key)


@router.get("/images")
async def list_edit_images(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List edited images."""
    from app.api.generation import GeneratedImageListResponse, _gen_to_response

    gen_service = get_generation_service(db, current_user.id)
    items = gen_service.get_generated_images(mode="edit", skip=skip, limit=limit)
    total = gen_service.count_generated_images(mode="edit")
    return GeneratedImageListResponse(
        items=[_gen_to_response(g, db) for g in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/images/bulk-delete")
async def bulk_delete_edit_images(
    request: BulkDeleteImagesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete multiple edited images."""
    gen_service = get_generation_service(db, current_user.id)
    deleted = await gen_service.bulk_delete_generated_images(request.image_ids)
    return {"deleted": deleted}


@router.get("/images/{gen_id}")
async def get_edit_image(
    gen_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single edited image detail."""
    from app.api.generation import _gen_to_response

    gen_service = get_generation_service(db, current_user.id)
    gen = gen_service.get_generated_image(gen_id)
    if not gen:
        raise HTTPException(status_code=404, detail="Edited image not found")
    return _gen_to_response(gen, db)


@router.delete("/images/{gen_id}", status_code=204)
async def delete_edit_image(
    gen_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an edited image."""
    gen_service = get_generation_service(db, current_user.id)
    if not await gen_service.delete_generated_image(gen_id):
        raise HTTPException(status_code=404, detail="Edited image not found")


@router.get("/images/{gen_id}/file")
async def serve_edit_image(
    gen_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_from_token_param),
):
    """Serve edited image file."""
    from app.services.storage import get_storage_service

    gen_service = get_generation_service(db, current_user.id)
    gen = gen_service.get_generated_image(gen_id)
    if not gen or not gen.object_key:
        raise HTTPException(status_code=404, detail="Edited image file not found")

    storage = get_storage_service()
    response = storage.get_file_response_with_filename(
        "generated", gen.object_key, gen.mime_type or "image/png",
        download_filename=gen.object_key,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="File not found")
    return response


@router.get("/thumbnails/{filename}")
async def serve_edit_thumbnail(
    filename: str,
    current_user: User = Depends(get_current_user_from_token_param),
):
    """Serve edited image thumbnail."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    response = storage.get_file_response("generated_thumbnails", filename, "image/jpeg")
    if response is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return response
