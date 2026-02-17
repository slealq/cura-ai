"""Vision API endpoints for direct AI vision model interaction."""
import logging
import time
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.services.billing_service import InsufficientBalanceError
from app.services.vision_service import get_vision_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vision", tags=["vision"])


# --- Schemas ---


class VisionAnalyzeRequest(BaseModel):
    """Request to analyze an image with a vision model."""

    source_image_id: int | None = None
    source_generated_id: int | None = None
    source_upload_key: str | None = None
    provider: str = "openai"
    model: str | None = None
    mode: Literal["tag", "describe", "custom"] = "describe"
    custom_prompt: str | None = Field(None, max_length=4000)
    tag_prompt: str | None = Field(None, max_length=8000)
    description_prompt: str | None = Field(None, max_length=8000)


class VisionTagResult(BaseModel):
    id: int
    mode: Literal["tag"] = "tag"
    tags: list[str]
    model: str
    duration_ms: int | None = None


class VisionDescribeResult(BaseModel):
    id: int
    mode: Literal["describe", "custom"]
    description: str
    model: str
    duration_ms: int | None = None


class VisionSourceUploadResponse(BaseModel):
    object_key: str


class VisionResultResponse(BaseModel):
    id: int
    mode: str
    provider: str
    model: str
    prompt_text: str | None = None
    result_tags: list[str] | None = None
    result_text: str | None = None
    duration_ms: int | None = None
    source_image_id: int | None = None
    source_generated_id: int | None = None
    source_object_key: str | None = None
    created_at: datetime


class VisionResultListResponse(BaseModel):
    items: list[VisionResultResponse]
    total: int
    skip: int
    limit: int


# --- Helpers ---


async def _load_image_bytes(
    request: VisionAnalyzeRequest,
    db: Session,
    user_id: int,
) -> tuple[bytes, str]:
    """Load image bytes and mime_type from the requested source."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()

    if request.source_image_id is not None:
        from app.services.image_service import get_image_service

        img_service = get_image_service(db, user_id)
        image = img_service.get_image(request.source_image_id)
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        image_data = await storage.get_image(image.object_key)
        return image_data, image.mime_type or "image/jpeg"

    if request.source_generated_id is not None:
        from app.services.generation_service import get_generation_service

        gen_service = get_generation_service(db, user_id)
        gen = gen_service.get_generated_image(request.source_generated_id)
        if not gen or not gen.object_key:
            raise HTTPException(status_code=404, detail="Generated image not found")
        image_data = await storage.get_generated_image(gen.object_key)
        return image_data, gen.mime_type or "image/png"

    if request.source_upload_key is not None:
        try:
            image_data = await storage.get_generated_image(request.source_upload_key)
            ext = request.source_upload_key.rsplit(".", 1)[-1].lower()
            mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}
            mime_type = mime_map.get(ext, "image/jpeg")
            return image_data, mime_type
        except Exception:
            raise HTTPException(status_code=404, detail="Uploaded source image not found")

    raise HTTPException(status_code=400, detail="No image source provided")


# --- Endpoints ---


@router.post("/analyze")
async def analyze_image(
    request: VisionAnalyzeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Analyze an image using a vision AI model (tag, describe, or custom prompt)."""
    # Validate exactly one source
    sources = [request.source_image_id, request.source_generated_id, request.source_upload_key]
    if sum(s is not None for s in sources) != 1:
        raise HTTPException(status_code=400, detail="Exactly one image source must be provided")

    if request.mode == "custom" and not request.custom_prompt:
        raise HTTPException(status_code=400, detail="custom_prompt is required for custom mode")

    # Load image bytes
    image_data, mime_type = await _load_image_bytes(request, db, current_user.id)

    # Resolve prompts: use request overrides (guidance text) → compose with system template,
    # or fall back to the active preset's composed prompts.
    from app.providers import get_describer, get_tagger
    from app.services.settings_service import (
        compose_description_prompt,
        compose_tag_prompt,
        get_settings_service,
    )

    settings_service = get_settings_service(db, current_user.id)
    vision_service = get_vision_service(db, current_user.id)

    try:
        if request.mode == "tag":
            if request.tag_prompt is not None:
                prompt = compose_tag_prompt(request.tag_prompt)
            else:
                prompt = settings_service.get_tag_prompt()
            tagger = get_tagger(
                provider=request.provider, db=db, user_id=current_user.id, model=request.model,
            )
            t0 = time.perf_counter()
            result = await tagger.tag_image(image_data, mime_type, prompt)
            duration_ms = int((time.perf_counter() - t0) * 1000)

            saved = vision_service.create_result(
                mode="tag",
                provider=request.provider,
                model=result.model,
                prompt_text=prompt,
                result_tags=result.tags,
                duration_ms=duration_ms,
                source_image_id=request.source_image_id,
                source_generated_id=request.source_generated_id,
                source_object_key=request.source_upload_key,
            )
            return VisionTagResult(id=saved.id, tags=result.tags, model=result.model, duration_ms=duration_ms)

        elif request.mode == "describe":
            if request.description_prompt is not None:
                prompt = compose_description_prompt(request.description_prompt)
            else:
                prompt = settings_service.get_description_prompt()
            describer = get_describer(
                provider=request.provider, db=db, user_id=current_user.id, model=request.model,
            )
            t0 = time.perf_counter()
            result = await describer.describe_image(image_data, mime_type, prompt)
            duration_ms = int((time.perf_counter() - t0) * 1000)

            saved = vision_service.create_result(
                mode="describe",
                provider=request.provider,
                model=result.model,
                prompt_text=prompt,
                result_text=result.description,
                duration_ms=duration_ms,
                source_image_id=request.source_image_id,
                source_generated_id=request.source_generated_id,
                source_object_key=request.source_upload_key,
            )
            return VisionDescribeResult(id=saved.id, mode="describe", description=result.description, model=result.model, duration_ms=duration_ms)

        else:  # custom
            prompt = request.custom_prompt
            describer = get_describer(
                provider=request.provider, db=db, user_id=current_user.id, model=request.model,
            )
            t0 = time.perf_counter()
            result = await describer.describe_image(image_data, mime_type, prompt)
            duration_ms = int((time.perf_counter() - t0) * 1000)

            saved = vision_service.create_result(
                mode="custom",
                provider=request.provider,
                model=result.model,
                prompt_text=prompt,
                result_text=result.description,
                duration_ms=duration_ms,
                source_image_id=request.source_image_id,
                source_generated_id=request.source_generated_id,
                source_object_key=request.source_upload_key,
            )
            return VisionDescribeResult(id=saved.id, mode="custom", description=result.description, model=result.model, duration_ms=duration_ms)

    except InsufficientBalanceError:
        raise HTTPException(status_code=402, detail="Insufficient credits")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Vision analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Vision analysis failed: {e}")


@router.get("/results", response_model=VisionResultListResponse)
async def list_results(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List vision analysis results for the current user, newest first."""
    vision_service = get_vision_service(db, current_user.id)
    items = vision_service.list_results(skip=skip, limit=limit)
    total = vision_service.count_results()
    return VisionResultListResponse(
        items=[
            VisionResultResponse(
                id=r.id,
                mode=r.mode,
                provider=r.provider,
                model=r.model,
                prompt_text=r.prompt_text,
                result_tags=r.result_tags,
                result_text=r.result_text,
                duration_ms=r.duration_ms,
                source_image_id=r.source_image_id,
                source_generated_id=r.source_generated_id,
                source_object_key=r.source_object_key,
                created_at=r.created_at,
            )
            for r in items
        ],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.delete("/results/{result_id}", status_code=204)
async def delete_result(
    result_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a single vision analysis result."""
    vision_service = get_vision_service(db, current_user.id)
    if not vision_service.delete_result(result_id):
        raise HTTPException(status_code=404, detail="Result not found")


@router.post("/upload-source", response_model=VisionSourceUploadResponse)
async def upload_source_image(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload a source image for vision analysis. Returns an object_key for use in analyze requests."""
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {file.content_type}")

    data = await file.read()
    max_size = 30 * 1024 * 1024  # 30MB
    if len(data) > max_size:
        raise HTTPException(status_code=400, detail="File too large (max 30MB)")

    ext = file.content_type.split("/")[-1] if file.content_type else "png"
    if ext == "jpeg":
        ext = "jpg"
    object_key = f"vision-sources/{uuid.uuid4().hex}.{ext}"

    from app.services.storage import get_storage_service

    storage = get_storage_service()
    await storage.save_generated_image(data, object_key, file.content_type or "image/png")

    return VisionSourceUploadResponse(object_key=object_key)
