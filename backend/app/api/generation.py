"""Generation API endpoints for LoRA training, image generation, and evaluation."""
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, model_validator
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
from app.workers.dispatch import dispatch

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/generation", tags=["generation"])


# --- Schemas ---


class ExpandPromptRequest(BaseModel):
    """Request to expand a terse prompt into a detailed image generation prompt."""

    prompt: str = Field(..., min_length=1)


class ExpandPromptResponse(BaseModel):
    """Response with the expanded prompt."""

    expanded_prompt: str


class TrainLoraRequest(BaseModel):
    """Request to start LoRA training from a folder or cluster."""

    name: str = Field(..., min_length=1, max_length=256)
    trigger_word: str | None = Field(None, max_length=128)
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
    example_prompts: list[str] | None = None

    @model_validator(mode="after")
    def validate_trigger_word_for_flux(self) -> "TrainLoraRequest":
        if self.base_model == "flux-dev" and not self.trigger_word:
            raise ValueError("trigger_word is required for flux-dev base model")
        return self


class LoraInput(BaseModel):
    """A single LoRA selection for generation."""

    lora_model_id: int
    lora_scale: float = Field(1.0, ge=0.0, le=2.0)


class LoraUsed(BaseModel):
    """LoRA info returned in generated image responses."""

    lora_model_id: int
    lora_model_name: str
    lora_scale: float


class GenerateRequest(BaseModel):
    """Request to generate images."""

    prompt: str = Field(..., min_length=1)
    negative_prompt: str | None = None
    lora_model_id: int | None = None
    lora_scale: float = Field(1.0, ge=0.0, le=2.0)
    loras: list[LoraInput] | None = None
    base_model: str | None = None
    width: int = Field(1024, ge=256, le=2048)
    height: int = Field(1024, ge=256, le=2048)
    num_inference_steps: int = Field(28, ge=1, le=100)
    guidance_scale: float = Field(3.5, ge=0.0, le=20.0)
    seed: int | None = None
    num_images: int = Field(1, ge=1, le=8)
    resolution: str | None = None
    aspect_ratio: str | None = None
    safety_tolerance: str | None = None
    enable_web_search: bool | None = None

    @model_validator(mode="after")
    def normalize_loras(self) -> "GenerateRequest":
        """Normalize legacy lora_model_id into loras list. Max 2 LoRAs."""
        if self.loras:
            # loras field takes priority — clear legacy fields
            self.lora_model_id = None
            if len(self.loras) > 2:
                raise ValueError("Maximum 2 LoRAs allowed per generation")
        elif self.lora_model_id:
            # Legacy single LoRA — wrap into loras list
            self.loras = [LoraInput(lora_model_id=self.lora_model_id, lora_scale=self.lora_scale)]
            self.lora_model_id = None
        return self


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
    trigger_word: str | None
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
    # Weights storage
    weights_object_key: str | None = None
    file_size: int | None = None
    file_hash: str | None = None
    weights_downloaded_at: str | None = None
    has_local_weights: bool = False
    example_prompts: list[str] | None = None
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
    loras: list[LoraUsed] = Field(default_factory=list)
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
    cost_sparks: float | None = None
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
        weights_object_key=lora.weights_object_key,
        file_size=lora.file_size,
        file_hash=lora.file_hash,
        weights_downloaded_at=lora.weights_downloaded_at.isoformat() if lora.weights_downloaded_at else None,
        has_local_weights=lora.weights_object_key is not None,
        example_prompts=lora.example_prompts,
        created_at=lora.created_at.isoformat(),
        training_started_at=lora.training_started_at.isoformat() if lora.training_started_at else None,
        training_completed_at=lora.training_completed_at.isoformat() if lora.training_completed_at else None,
        updated_at=lora.updated_at.isoformat(),
    )


def _gen_to_response(gen, db: Session) -> GeneratedImageResponse:
    from app.models.lora_model import LoraModel

    # Build loras list from generation_params if available
    loras_list: list[LoraUsed] = []
    params = gen.generation_params or {}
    if "loras" in params:
        for entry in params["loras"]:
            lora_id = entry.get("lora_model_id")
            lora_scale = entry.get("lora_scale", 1.0)
            lora_name = entry.get("lora_model_name", "")
            if not lora_name and lora_id:
                lora_row = db.query(LoraModel).filter(LoraModel.id == lora_id).first()
                lora_name = lora_row.name if lora_row else f"LoRA #{lora_id}"
            loras_list.append(LoraUsed(lora_model_id=lora_id, lora_model_name=lora_name, lora_scale=lora_scale))
    elif gen.lora_model_id:
        # Backward compat: old records without loras in params
        lora_name = gen.lora_model.name if gen.lora_model else f"LoRA #{gen.lora_model_id}"
        loras_list.append(LoraUsed(lora_model_id=gen.lora_model_id, lora_model_name=lora_name, lora_scale=gen.lora_scale or 1.0))

    # Get per-image cost from job (split evenly for batch jobs)
    cost_sparks: float | None = None
    if gen.job_id:
        job = db.query(Job).filter(Job.id == gen.job_id).first()
        if job:
            total_items = max(job.total_items, 1)
            if job.charged_sparks is not None:
                cost_sparks = round(job.charged_sparks / total_items, 1)
            elif job.charged_cost is not None:
                cost_sparks = round(float(job.charged_cost) / total_items, 1)

    return GeneratedImageResponse(
        id=gen.id,
        prompt=gen.prompt,
        negative_prompt=gen.negative_prompt,
        base_model=gen.base_model,
        generation_provider=gen.generation_provider,
        lora_model_id=gen.lora_model_id,
        lora_model_name=gen.lora_model.name if gen.lora_model else None,
        lora_scale=gen.lora_scale,
        loras=loras_list,
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
        cost_sparks=cost_sparks,
        created_at=gen.created_at.isoformat(),
        completed_at=gen.completed_at.isoformat() if gen.completed_at else None,
    )


# --- Prompt Expansion ---


@router.post("/expand-prompt", response_model=ExpandPromptResponse)
async def expand_prompt(
    request: ExpandPromptRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Expand a terse prompt into a detailed image generation prompt using AI."""
    from openai import AsyncOpenAI

    from app.providers import _resolve_config
    from app.services.billing_context import (
        get_trace_id,
        init_trace,
        make_idempotency_key,
        set_billing_user,
        set_trace_id,
    )
    from app.services.billing_orchestrator import ORCHESTRATOR_ENABLED_OPS, BillingOrchestrator
    from app.services.billing_service import BillingService, InsufficientBalanceError, ZeroCostEstimateError

    try:
        BillingService(db, current_user.id).check_balance_or_raise()
    except InsufficientBalanceError:
        raise HTTPException(status_code=402, detail="Insufficient credits")

    keys, _ = _resolve_config(db, current_user.id)
    openai_key = keys.get("openai")
    if not openai_key:
        raise HTTPException(status_code=400, detail="OpenAI API key not configured on the platform.")

    # Use language model settings from provider config
    settings_svc = get_settings_service(db, current_user.id)
    provider_config = settings_svc.get_provider_config()
    expansion_model = provider_config.get("openai_language_model", "gpt-4o-mini")
    expansion_max_tokens = provider_config.get("max_tokens_expansion", 500)

    client = AsyncOpenAI(api_key=openai_key)

    set_billing_user(current_user.id)
    init_trace()
    orch = BillingOrchestrator(db, current_user.id) if "expand_prompt" in ORCHESTRATOR_ENABLED_OPS else None
    decision = None
    if orch:
        try:
            idem_key = make_idempotency_key(current_user.id, get_trace_id(), "expand_prompt", None)
            decision, is_new = orch.create_decision(
                operation="expand_prompt",
                provider="openai",
                model=expansion_model,
                trace_id=get_trace_id(),
                idempotency_key=idem_key,
            )
            # No idempotency skip for expand_prompt — each call is intentionally unique
        except ZeroCostEstimateError:
            raise HTTPException(status_code=422, detail="Billing configuration error — cannot price this operation")

    try:
        response = await client.chat.completions.create(
            model=expansion_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a prompt engineer for AI image generation. "
                        "The user will give you a short, terse image idea. "
                        "Expand it into a single vivid paragraph suitable for an image generation model. "
                        "Add details about composition, lighting, style, mood, colors, and textures "
                        "while preserving the user's original intent. "
                        "Return ONLY the expanded prompt text with no commentary or explanation."
                    ),
                },
                {"role": "user", "content": request.prompt},
            ],
            max_tokens=expansion_max_tokens,
        )

        expanded = response.choices[0].message.content or ""
        usage = response.usage

        # Record billing
        if orch and decision and usage:
            orch.record_actual(
                decision.id,
                actual_input_tokens=usage.prompt_tokens,
                actual_output_tokens=usage.completion_tokens,
                defer_debit=False,
            )
        elif usage:
            # Fallback if orchestrator not enabled
            billing = BillingService(db, current_user.id)
            billing.record_usage(
                operation="expand_prompt",
                provider="openai",
                model=expansion_model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
            )

        return ExpandPromptResponse(expanded_prompt=expanded.strip())

    except HTTPException:
        raise
    except Exception as e:
        if orch and decision:
            orch.fail_decision(decision.id, str(e))
        logger.error(f"Failed to expand prompt: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to expand prompt: {str(e)}")
    finally:
        set_billing_user(None)
        set_trace_id(None)


# --- LoRA Routes ---


@router.post("/lora/train", status_code=201)
async def train_lora(request: TrainLoraRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Start LoRA training from a folder or cluster of images."""
    if not request.folder_id and not request.cluster_id:
        raise HTTPException(status_code=400, detail="Either folder_id or cluster_id is required")
    if request.folder_id and request.cluster_id:
        raise HTTPException(status_code=400, detail="Provide either folder_id or cluster_id, not both")

    image_count = 0
    job_params: dict = {"trigger_word": request.trigger_word or "", "base_model": request.base_model}

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

    # Save user-provided example prompts
    if request.example_prompts:
        lora.example_prompts = request.example_prompts
        db.commit()

    # Store lora_model_id in job parameters for frontend recovery buttons
    job.parameters = {**job.parameters, "lora_model_id": lora.id}

    # Dispatch Celery task
    from app.workers.generation_tasks import train_lora as train_lora_task
    task = dispatch(train_lora_task, lora.id, job.id, current_user.id)

    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "training_started",
        "lora_model_id": lora.id,
        "job_id": job.id,
    }


SUPPORTED_BASE_MODELS = {"flux-dev", "qwen-2.5"}


@router.post("/lora/upload", status_code=201)
async def upload_lora(
    name: str = Form(...),
    trigger_word: str | None = Form(None),
    base_model: str = Form("flux-dev"),
    description: str | None = Form(None),
    example_prompts: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload an external LoRA .safetensors file."""
    import asyncio
    import hashlib
    import tempfile
    import uuid
    from datetime import datetime
    from pathlib import Path

    from app.models.pipeline_log import LogCategory, LogLevel
    from app.services.log_service import write_log

    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".safetensors"):
        raise HTTPException(status_code=400, detail="File must be a .safetensors file")

    # Validate base model
    if base_model not in SUPPORTED_BASE_MODELS:
        raise HTTPException(status_code=400, detail=f"Unsupported base model. Must be one of: {', '.join(sorted(SUPPORTED_BASE_MODELS))}")

    # Read file bytes
    file_data = await file.read()
    if len(file_data) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    file_size = len(file_data)
    file_hash = hashlib.sha256(file_data).hexdigest()
    object_key = f"{uuid.uuid4().hex}.safetensors"

    # Ensure fal API key is set from user's stored key
    from app.providers import _resolve_config
    from app.providers.fal_provider import _ensure_fal_key
    keys, _ = _resolve_config(db, current_user.id)
    _ensure_fal_key(keys.get("fal"))

    # Upload to fal CDN via temp file (more reliable for large .safetensors files
    # than in-memory bytes — avoids CDN "content length zero" errors)
    try:
        import fal_client
        with tempfile.NamedTemporaryFile(suffix=".safetensors", delete=False) as tmp:
            tmp.write(file_data)
            tmp_path = tmp.name
        try:
            lora_url = await asyncio.to_thread(fal_client.upload_file, Path(tmp_path))
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        logger.error(f"Failed to upload LoRA to fal CDN: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to upload to fal CDN: {e}")

    write_log(
        LogCategory.TASK, f"LoRA '{name}' uploaded to fal CDN ({file_size} bytes)",
        level=LogLevel.INFO, operation="lora_upload_cdn", provider="fal",
        extra={"lora_url": lora_url, "file_hash": file_hash, "base_model": base_model},
        user_id=current_user.id,
    )

    # Save to our own storage
    try:
        from app.services.storage import get_storage_service
        storage = get_storage_service()
        await storage.save_lora_weights(file_data, object_key)
    except Exception as e:
        logger.warning(f"Failed to save LoRA weights to storage (CDN upload succeeded): {e}")
        write_log(
            LogCategory.TASK, f"LoRA '{name}' storage backup failed: {e}",
            level=LogLevel.WARNING, operation="lora_upload_storage",
            extra={"object_key": object_key, "error": str(e)},
            user_id=current_user.id,
        )

    # Parse example_prompts JSON string
    parsed_example_prompts = None
    if example_prompts:
        import json
        try:
            parsed_example_prompts = json.loads(example_prompts)
            if not isinstance(parsed_example_prompts, list):
                parsed_example_prompts = None
        except (json.JSONDecodeError, TypeError):
            parsed_example_prompts = None

    try:
        # Create LoRA model record
        gen_service = get_generation_service(db, current_user.id)
        lora = gen_service.create_lora_model(
            name=name,
            trigger_word=trigger_word or None,
            training_provider="upload",
            folder_id=None,
            cluster_id=None,
            base_model=base_model,
            description=description,
            training_config=None,
            training_images_count=0,
            job_id=None,
        )

        # Update with upload results
        lora.status = LoraModelStatus.UPLOADED
        lora.lora_url = lora_url
        lora.weights_object_key = object_key
        lora.lora_local_path = object_key
        lora.file_size = file_size
        lora.file_hash = file_hash
        lora.weights_downloaded_at = datetime.utcnow()
        if parsed_example_prompts:
            lora.example_prompts = parsed_example_prompts
        db.commit()
        db.refresh(lora)

        write_log(
            LogCategory.TASK, f"LoRA '{name}' model record created (id={lora.id})",
            level=LogLevel.INFO, operation="lora_upload_complete",
            extra={"lora_model_id": lora.id, "base_model": base_model, "status": "uploaded"},
            user_id=current_user.id,
        )
    except Exception as e:
        logger.error(f"Failed to create LoRA model record after CDN upload: {e}")
        write_log(
            LogCategory.TASK, f"LoRA '{name}' model record creation failed: {e}",
            level=LogLevel.ERROR, operation="lora_upload_create",
            extra={"error": str(e), "lora_url": lora_url},
            user_id=current_user.id,
        )
        raise HTTPException(status_code=500, detail=f"Model uploaded to CDN but failed to save record: {e}")

    try:
        return _lora_to_response(lora, db)
    except Exception as e:
        logger.error(f"LoRA upload succeeded (id={lora.id}) but response serialization failed: {e}")
        write_log(
            LogCategory.TASK, f"LoRA '{name}' response serialization failed: {e}",
            level=LogLevel.ERROR, operation="lora_upload_response",
            extra={"lora_model_id": lora.id, "error": str(e)},
            user_id=current_user.id,
        )
        # Model was saved — return a minimal success response
        return {
            "id": lora.id,
            "name": lora.name,
            "status": lora.status.value,
            "base_model": lora.base_model,
            "lora_url": lora.lora_url,
            "created_at": lora.created_at.isoformat(),
            "warning": f"Model saved but response serialization failed: {e}",
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
    """List LoRA models. Status supports comma-separated values (e.g. 'completed,uploaded')."""
    gen_service = get_generation_service(db, current_user.id)
    status_filter: LoraModelStatus | list[LoraModelStatus] | None = None
    if status:
        parts = [s.strip() for s in status.split(",") if s.strip()]
        if len(parts) == 1:
            status_filter = LoraModelStatus(parts[0])
        else:
            status_filter = [LoraModelStatus(p) for p in parts]
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
    trainer = get_trainer(lora.training_provider, db=db, base_model=lora.base_model, user_id=current_user.id)

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
            # Dispatch best-effort weights download
            from app.workers.generation_tasks import download_lora_weights as dl_task
            dispatch(dl_task, lora_id, current_user.id)
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
        task = dispatch(train_lora_task, lora_id, lora.job_id, current_user.id)
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
            parameters={"trigger_word": lora.trigger_word or "", "retry_of_lora_id": lora_id},
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
    task = dispatch(train_lora_task, lora_id, job.id, current_user.id)

    job.celery_task_id = task.id
    db.commit()

    return {"status": "retry_started", "lora_model_id": lora_id, "job_id": job.id}


@router.delete("/lora/{lora_id}", status_code=204)
async def delete_lora_model(lora_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a LoRA model."""
    gen_service = get_generation_service(db, current_user.id)
    if not gen_service.delete_lora_model(lora_id):
        raise HTTPException(status_code=404, detail="LoRA model not found")


@router.post("/lora/{lora_id}/download-weights")
async def download_lora_weights_endpoint(lora_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Download and store LoRA weights from provider CDN."""
    gen_service = get_generation_service(db, current_user.id)
    lora = gen_service.get_lora_model(lora_id)
    if not lora:
        raise HTTPException(status_code=404, detail="LoRA model not found")
    if lora.status not in (LoraModelStatus.COMPLETED, LoraModelStatus.UPLOADED):
        raise HTTPException(status_code=400, detail="LoRA model is not completed")
    if not lora.lora_url:
        raise HTTPException(status_code=400, detail="No lora_url available")
    if lora.weights_object_key:
        raise HTTPException(status_code=400, detail="Weights already downloaded")

    from app.workers.generation_tasks import download_lora_weights as dl_task
    dispatch(dl_task, lora_id, current_user.id)
    return {"status": "download_started"}


@router.post("/lora/download-all-weights")
async def download_all_lora_weights(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Download weights for all completed LoRA models that don't have local weights."""
    from app.models.lora_model import LoraModel

    models = (
        db.query(LoraModel)
        .filter(
            LoraModel.user_id == current_user.id,
            LoraModel.status.in_([LoraModelStatus.COMPLETED, LoraModelStatus.UPLOADED]),
            LoraModel.lora_url.isnot(None),
            LoraModel.weights_object_key.is_(None),
        )
        .all()
    )

    from app.workers.generation_tasks import download_lora_weights as dl_task
    for model in models:
        dispatch(dl_task, model.id, current_user.id)

    return {"status": "downloads_queued", "count": len(models)}


@router.get("/lora/{lora_id}/weights")
async def serve_lora_weights(lora_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user_from_token_param)):
    """Serve LoRA weights file for download."""
    from app.services.storage import get_storage_service

    gen_service = get_generation_service(db, current_user.id)
    lora = gen_service.get_lora_model(lora_id)
    if not lora or not lora.weights_object_key:
        raise HTTPException(status_code=404, detail="LoRA weights not found")

    # Build a friendly download filename
    safe_name = lora.name.replace(" ", "_").replace("/", "_")
    download_filename = f"{safe_name}_{lora.base_model}.safetensors"

    storage = get_storage_service()
    response = storage.get_file_response_with_filename(
        "lora_weights", lora.weights_object_key, "application/octet-stream",
        download_filename=download_filename,
    )
    if response is None:
        raise HTTPException(status_code=404, detail="Weights file not found in storage")
    return response


# --- Generation Routes ---


@router.post("/generate", status_code=201)
async def generate_images(request: GenerateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Generate 1-8 images."""
    gen_service = get_generation_service(db, current_user.id)

    # Determine effective base_model
    effective_base_model = request.base_model or "flux-dev"

    # Validate LoRAs if specified
    loras_for_params: list[dict] = []
    first_lora_id: int | None = None
    first_lora_scale: float = 1.0

    if request.loras:
        base_models_seen: set[str] = set()
        for lora_input in request.loras:
            lora = gen_service.get_lora_model(lora_input.lora_model_id)
            if not lora:
                raise HTTPException(status_code=404, detail=f"LoRA model {lora_input.lora_model_id} not found")
            if lora.status not in (LoraModelStatus.COMPLETED, LoraModelStatus.UPLOADED):
                raise HTTPException(status_code=400, detail=f"LoRA model '{lora.name}' is not ready (status: {lora.status.value})")
            if not lora.lora_url:
                raise HTTPException(status_code=400, detail=f"LoRA model '{lora.name}' has no weights URL")
            base_models_seen.add(lora.base_model)
            loras_for_params.append({
                "lora_model_id": lora.id,
                "lora_model_name": lora.name,
                "lora_scale": lora_input.lora_scale,
            })

        if len(base_models_seen) > 1:
            raise HTTPException(status_code=400, detail="All LoRAs must use the same base model")

        # Infer base_model from LoRAs if not explicitly set
        lora_base = base_models_seen.pop()
        if not request.base_model:
            effective_base_model = lora_base
        elif lora_base != effective_base_model:
            raise HTTPException(
                status_code=400,
                detail=f"LoRA models are trained on '{lora_base}' but generation requested '{effective_base_model}'. They must match.",
            )

        # Backward compat columns: set to first LoRA
        first_lora_id = request.loras[0].lora_model_id
        first_lora_scale = request.loras[0].lora_scale

    # Get generation defaults from settings
    settings_service = get_settings_service(db, current_user.id)
    settings_service.get_generation_config()
    provider = settings.default_generation_provider

    # Build generation_params
    gen_params: dict = {
        "width": request.width,
        "height": request.height,
        "num_inference_steps": request.num_inference_steps,
        "guidance_scale": request.guidance_scale,
        "seed": request.seed,
    }
    if request.resolution:
        gen_params["resolution"] = request.resolution
    if request.aspect_ratio:
        gen_params["aspect_ratio"] = request.aspect_ratio
    if request.safety_tolerance:
        gen_params["safety_tolerance"] = request.safety_tolerance
    if request.enable_web_search is not None:
        gen_params["enable_web_search"] = request.enable_web_search
    if loras_for_params:
        gen_params["loras"] = loras_for_params

    # Create job
    try:
        job = Job(
            job_type=JobType.BATCH_GENERATE if request.num_images > 1 else JobType.GENERATE_IMAGE,
            status=JobStatus.PENDING,
            total_items=request.num_images,
            parameters={
                "prompt": request.prompt[:200],
                "num_images": request.num_images,
                "base_model": effective_base_model,
                "lora_model_id": first_lora_id,
                **({"loras": loras_for_params} if loras_for_params else {}),
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
            lora_model_id=first_lora_id,
            lora_scale=first_lora_scale,
            generation_params=gen_params,
            job_id=job.id,
        )
        gen_ids.append(gen.id)

    # Dispatch Celery tasks
    from app.workers.generation_tasks import batch_generate
    from app.workers.generation_tasks import generate_image as gen_task

    if request.num_images == 1:
        task = dispatch(gen_task, gen_ids[0], job.id, current_user.id)
        job.celery_task_id = task.id
    else:
        task = dispatch(batch_generate, gen_ids, job.id, current_user.id)
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
        mode="generate",
    )
    total = gen_service.count_generated_images(
        lora_model_id=lora_model_id,
        status=status_filter,
        mode="generate",
    )
    return GeneratedImageListResponse(
        items=[_gen_to_response(g, db) for g in items],
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
    return _gen_to_response(gen, db)


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
    if lora.status not in (LoraModelStatus.COMPLETED, LoraModelStatus.UPLOADED):
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
    task = dispatch(evaluate_task, evaluation.id, job.id, current_user.id)

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
