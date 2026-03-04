"""Image API endpoints."""
import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session, lazyload

from app.core.config import get_settings
from app.core.security import get_current_user, get_current_user_from_token_param
from app.db.base import get_db
from app.models import Image, ImageSource, ImageStatus, Job, JobStatus, JobType
from app.models.pipeline_log import LogCategory
from app.models.user import User
from app.schemas import (
    BatchUploadResponse,
    ImageListResponse,
    ImageResponse,
    PipelineStats,
    ProcessingCostOperation,
    ProcessingCostResponse,
    StepResponse,
    UploadResponse,
)
from app.services.folder_service import get_folder_service
from app.services.image_service import get_image_service
from app.services.log_service import write_log
from app.workers.dispatch import dispatch
from app.workers.tasks import (
    describe_image,
    embed_image,
    process_image_pipeline,
    process_ingest_batch,
    tag_image,
)

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/images", tags=["images"])


@router.post("/upload", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    folder_id: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload a single image for processing."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    image_service = get_image_service(db, current_user.id)

    try:
        file_data = await file.read()
        image = await image_service.ingest_image(
            file_data=file_data,
            filename=file.filename or "upload.jpg",
            source=ImageSource.UPLOAD,
        )

        if folder_id:
            folder_service = get_folder_service(db, current_user.id)
            folder_service.add_images_to_folder(folder_id, [image.id])

        return UploadResponse(
            image_id=image.id,
            filename=file.filename or "upload.jpg",
            status="ingested",
            message="Image uploaded successfully",
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/batch", response_model=BatchUploadResponse)
async def upload_images_batch(
    files: list[UploadFile] = File(...),
    folder_id: int | None = Query(None),
    new_folder_name: str | None = Query(None),
    job_id: int | None = Query(None),
    total_items: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload multiple images for processing.

    Fast ingest: saves raw files and creates PENDING records, then dispatches
    Celery tasks for heavy processing (thumbnails, dimensions, perceptual hash).
    Returns immediately so the frontend isn't blocked.

    Folder assignment is deferred: if folder_id or new_folder_name is provided
    on the first chunk, the folder is created/assigned only after all images
    finish ingesting (in _finish_ingest_job_item). This prevents empty folders
    from appearing in the UI before thumbnails are ready.
    """
    chunk_start = time.monotonic()
    image_service = get_image_service(db, current_user.id)

    # Create or load the INGEST job for tracking
    if job_id is not None:
        job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
    else:
        # Store folder info in job parameters for deferred assignment
        params = {}
        if folder_id is not None:
            params["folder_id"] = folder_id
        if new_folder_name:
            params["new_folder_name"] = new_folder_name.strip()

        job = Job(
            job_type=JobType.INGEST,
            status=JobStatus.RUNNING,
            started_at=datetime.utcnow(),
            total_items=total_items or len(files),
            progress=0,
            user_id=current_user.id,
            parameters=params,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

    filenames = [f.filename or "upload.jpg" for f in files]
    logger.info(
        f"Batch upload chunk: {len(files)} files, job_id={job.id}, "
        f"progress_before={job.progress}/{job.total_items}, "
        f"files={filenames}"
    )

    uploaded = []
    failed = []
    new_image_ids = []  # Non-duplicate images that need Celery processing

    for file in files:
        if not file.content_type or not file.content_type.startswith("image/"):
            failed.append({"filename": file.filename, "error": "Not an image file"})
            continue

        try:
            file_data = await file.read()
            image = await image_service.fast_ingest(
                file_data=file_data,
                filename=file.filename or "upload.jpg",
                source=ImageSource.UPLOAD,
            )

            if image is None:
                # Duplicate — still count as "uploaded" (existing image)
                existing = db.query(Image).filter(
                    Image.file_hash == image_service.storage.compute_file_hash(file_data),
                    Image.user_id == current_user.id,
                ).first()
                uploaded.append(
                    UploadResponse(
                        image_id=existing.id if existing else 0,
                        filename=file.filename or "upload.jpg",
                        status="duplicate",
                        message="Duplicate image skipped",
                    )
                )
            else:
                uploaded.append(
                    UploadResponse(
                        image_id=image.id,
                        filename=file.filename or "upload.jpg",
                        status="pending",
                        message="Image accepted, processing queued",
                    )
                )
                new_image_ids.append(image.id)
            # Commit each image individually to avoid long-running transactions
            # (Azure blob uploads block for seconds per file)
            db.commit()
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            db.rollback()
            failed.append({"filename": file.filename, "error": str(e)})

    # Re-fetch job in case a rollback detached it
    job = db.query(Job).filter(Job.id == job.id).first()

    # Chunk timing data
    chunk_elapsed_ms = round((time.monotonic() - chunk_start) * 1000)
    now_iso = datetime.utcnow().isoformat()
    n_new = len(new_image_ids)
    n_dup = sum(1 for u in uploaded if u.status == "duplicate")
    n_fail = len(failed)

    # Track image IDs + observability counters on the job with row lock
    # to serialize parallel chunk writers (fixes race on job.result merge)
    all_chunk_ids = [u.image_id for u in uploaded if u.image_id > 0]
    locked_job = db.query(Job).options(lazyload(Job.image)).filter(Job.id == job.id).with_for_update().first()
    prev = locked_job.result or {}
    chunk_idx = prev.get("chunks_received", 0)
    locked_job.result = {
        **prev,
        "image_ids": prev.get("image_ids", []) + new_image_ids,
        "all_upload_ids": prev.get("all_upload_ids", []) + all_chunk_ids,
        "first_chunk_at": prev.get("first_chunk_at", now_iso),
        "last_chunk_at": now_iso,
        "total_received": prev.get("total_received", 0) + len(files),
        "new_count": prev.get("new_count", 0) + n_new,
        "duplicate_count": prev.get("duplicate_count", 0) + n_dup,
        "failed_count": prev.get("failed_count", 0) + n_fail,
        "chunks_received": chunk_idx + 1,
        "chunk_timings": prev.get("chunk_timings", []) + [{
            "chunk_idx": chunk_idx,
            "n_files": len(files),
            "n_new": n_new,
            "n_dup": n_dup,
            "n_fail": n_fail,
            "api_ms": chunk_elapsed_ms,
        }],
    }
    db.commit()

    # Dispatch a single batch Celery task for all new images in this chunk
    if new_image_ids:
        dispatch(process_ingest_batch, new_image_ids, current_user.id, job.id)

    # Immediately count items that won't go through Celery (duplicates + failures).
    # Only new images are counted by _finish_ingest_job_item in the Celery task.
    n_immediate = (len(uploaded) - len(new_image_ids)) + len(failed)
    if n_immediate > 0 and job.total_items:
        db.execute(
            Job.__table__.update()
            .where(Job.id == job.id)
            .values(progress=Job.progress + n_immediate)
        )
        db.commit()
        # Re-fetch to see updated progress
        job = db.query(Job).filter(Job.id == job.id).first()

        # Check if job is done (e.g. all items in this chunk were duplicates/failures
        # and no Celery tasks remain from earlier chunks)
        if job.progress >= job.total_items and job.status not in (
            JobStatus.COMPLETED, JobStatus.FAILED,
        ):
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.result = {**(job.result or {}), "processing_done_at": datetime.utcnow().isoformat()}
            db.commit()
            from app.workers.tasks import _assign_folder_on_completion
            _assign_folder_on_completion(db, job)

    write_log(
        category=LogCategory.TASK,
        message=(
            f"Upload chunk {chunk_idx + 1}: {len(files)} files "
            f"({n_new} new, {n_dup} dup, {n_fail} fail) in {chunk_elapsed_ms}ms"
        ),
        task_name="upload_images_batch",
        job_id=job.id,
        duration_ms=chunk_elapsed_ms,
        user_id=current_user.id,
    )

    logger.info(
        f"Batch upload chunk done: job_id={job.id}, "
        f"uploaded={len(uploaded)}, failed={len(failed)}, "
        f"new_images={len(new_image_ids)} dispatched to Celery"
    )

    # Folder assignment is deferred to job completion (_finish_ingest_job_item)
    return BatchUploadResponse(
        uploaded=uploaded,
        failed=failed,
        job_id=job.id,
    )


@router.get("", response_model=ImageListResponse)
async def list_images(
    status: ImageStatus | None = None,
    min_status: ImageStatus | None = None,
    max_status: ImageStatus | None = None,
    source: ImageSource | None = None,
    in_folder: bool | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List images with optional filtering."""
    image_service = get_image_service(db, current_user.id)
    images = image_service.get_images(
        status=status,
        min_status=min_status,
        max_status=max_status,
        source=source,
        in_folder=in_folder,
        skip=skip,
        limit=limit,
    )
    total = image_service.count_images(status=status, min_status=min_status, max_status=max_status, in_folder=in_folder)

    return ImageListResponse(
        items=[ImageResponse.model_validate(img) for img in images],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/stats", response_model=PipelineStats)
async def get_pipeline_stats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get pipeline processing statistics."""
    image_service = get_image_service(db, current_user.id)
    from app.services.cluster_service import get_cluster_service
    cluster_service = get_cluster_service(db, current_user.id)

    return PipelineStats(
        total_images=image_service.count_images(),
        pending=image_service.count_images(ImageStatus.PENDING),
        ingested=image_service.count_images(ImageStatus.INGESTED),
        tagged=image_service.count_images(ImageStatus.TAGGED),
        described=image_service.count_images(ImageStatus.DESCRIBED),
        embedded=image_service.count_images(ImageStatus.EMBEDDED),
        clustered=image_service.count_images(ImageStatus.CLUSTERED),
        failed=image_service.count_images(ImageStatus.FAILED),
        total_clusters=cluster_service.count_clusters(),
    )


@router.get("/{image_id}", response_model=ImageResponse)
async def get_image(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get image by ID."""
    image_service = get_image_service(db, current_user.id)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    return ImageResponse.model_validate(image)


@router.get("/{image_id}/folders")
async def get_image_folders(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get folders that contain this image."""
    folder_service = get_folder_service(db, current_user.id)
    folders = folder_service.get_image_folders(image_id)
    return [{"id": f.id, "name": f.name} for f in folders]


@router.get("/{image_id}/processing-costs", response_model=ProcessingCostResponse)
async def get_processing_costs(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get per-image processing cost breakdown from usage records."""
    from app.models.billing import UsageRecord
    from app.models.pipeline_log import PipelineLog

    # Verify image belongs to user
    image_service = get_image_service(db, current_user.id)
    image = image_service.get_image(image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Join UsageRecord → PipelineLog where PipelineLog.image_id matches
    records = (
        db.query(UsageRecord)
        .join(PipelineLog, UsageRecord.pipeline_log_id == PipelineLog.id)
        .filter(
            PipelineLog.image_id == image_id,
            PipelineLog.user_id == current_user.id,
        )
        .order_by(UsageRecord.created_at)
        .all()
    )

    # Always compute fractional sparks from charged_cost to avoid per-operation
    # ceiling inflation (delta_sparks is math.ceil'd per-decision, which overstates
    # individual costs — e.g. 0.54+1.25+0.01=1.80 displayed as 1+2+1=4).
    usd_to_sparks = 1000

    operations = []
    total_sparks = 0.0
    for r in records:
        sparks = round(float(r.charged_cost) * usd_to_sparks, 2)
        total_sparks += sparks
        operations.append(ProcessingCostOperation(
            operation=r.operation,
            provider=r.provider,
            model=r.model,
            sparks=sparks,
            input_tokens=r.input_tokens,
            output_tokens=r.output_tokens,
        ))

    return ProcessingCostResponse(operations=operations, total_sparks=round(total_sparks, 2))


class BatchDeleteRequest(BaseModel):
    image_ids: list[int]


@router.post("/batch-delete")
async def batch_delete_images(request: BatchDeleteRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete multiple images."""
    image_service = get_image_service(db, current_user.id)
    deleted = image_service.delete_images_batch(request.image_ids)
    return {"status": "deleted", "deleted": deleted}


@router.delete("/{image_id}")
async def delete_image(image_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete an image."""
    image_service = get_image_service(db, current_user.id)

    if not image_service.delete_image(image_id):
        raise HTTPException(status_code=404, detail="Image not found")

    return {"status": "deleted", "image_id": image_id}


@router.get("/{image_id}/similar", response_model=list[ImageResponse])
async def get_similar_images(
    image_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get images similar to the specified image based on embeddings."""
    from sqlalchemy import text

    image_service = get_image_service(db, current_user.id)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.image_metadata or image.image_metadata.embedding is None:
        raise HTTPException(status_code=400, detail="Image has no embedding")

    # Use pgvector to find similar images
    embedding = image.image_metadata.embedding
    embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"

    query = text("""
        SELECT i.id
        FROM images i
        JOIN image_metadata m ON i.id = m.image_id
        WHERE i.id != :image_id
        AND i.user_id = :user_id
        AND m.embedding IS NOT NULL
        ORDER BY m.embedding <-> :embedding
        LIMIT :limit
    """)

    result = db.execute(
        query,
        {"image_id": image_id, "user_id": current_user.id, "embedding": embedding_str, "limit": limit}
    )
    similar_ids = [row[0] for row in result]

    similar_images = image_service.get_images_by_ids(similar_ids)

    return [ImageResponse.model_validate(img) for img in similar_images]


class ReprocessRequest(BaseModel):
    """Request to reprocess an image."""

    tag_prompt: str | None = None
    description_prompt: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens_tag: int | None = None
    max_tokens_describe: int | None = None


@router.post("/{image_id}/reprocess", response_model=StepResponse)
async def reprocess_image(
    image_id: int,
    request: ReprocessRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reprocess an image through the pipeline with optional prompt overrides."""
    image_service = get_image_service(db, current_user.id)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    tag_prompt = request.tag_prompt if request else None
    description_prompt = request.description_prompt if request else None
    provider = request.provider if request else None
    model = request.model if request else None
    temperature = request.temperature if request else None
    max_tokens_tag = request.max_tokens_tag if request else None
    max_tokens_describe = request.max_tokens_describe if request else None

    # Create job record
    job = Job(
        job_type=JobType.REPROCESS,
        status=JobStatus.PENDING,
        image_id=image_id,
        total_items=1,
        parameters={"tag_prompt": tag_prompt, "description_prompt": description_prompt, "provider": provider, "model": model, "temperature": temperature, "max_tokens_tag": max_tokens_tag, "max_tokens_describe": max_tokens_describe},
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Reset status and queue for reprocessing
    image_service.update_status(image_id, ImageStatus.INGESTED)
    task = dispatch(process_image_pipeline, image_id, tag_prompt=tag_prompt, description_prompt=description_prompt, provider=provider, model=model, temperature=temperature, max_tokens_tag=max_tokens_tag, max_tokens_describe=max_tokens_describe, job_id=job.id, user_id=current_user.id)
    job.celery_task_id = task.id
    db.commit()

    return StepResponse(status="queued", image_id=image_id, step="reprocess", job_id=job.id)


class TagRequest(BaseModel):
    """Request to tag an image."""

    tag_prompt: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class DescribeRequest(BaseModel):
    """Request to describe an image."""

    description_prompt: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


TAG_ALLOWED = {ImageStatus.INGESTED, ImageStatus.TAGGED, ImageStatus.DESCRIBED, ImageStatus.EMBEDDED, ImageStatus.CLUSTERED, ImageStatus.FAILED}
DESCRIBE_ALLOWED = {ImageStatus.TAGGED, ImageStatus.DESCRIBED, ImageStatus.EMBEDDED, ImageStatus.CLUSTERED, ImageStatus.FAILED}
EMBED_ALLOWED = {ImageStatus.DESCRIBED, ImageStatus.EMBEDDED, ImageStatus.CLUSTERED, ImageStatus.FAILED}


@router.post("/{image_id}/tag", response_model=StepResponse)
async def tag_image_endpoint(
    image_id: int,
    request: TagRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Tag an image with structured metadata."""
    image_service = get_image_service(db, current_user.id)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if image.status not in TAG_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Image status '{image.status}' does not allow tagging")

    tag_prompt = request.tag_prompt if request else None
    provider = request.provider if request else None
    model = request.model if request else None
    temperature = request.temperature if request else None
    max_tokens = request.max_tokens if request else None

    job = Job(
        job_type=JobType.TAG,
        status=JobStatus.PENDING,
        image_id=image_id,
        total_items=1,
        parameters={"tag_prompt": tag_prompt, "provider": provider, "model": model, "temperature": temperature, "max_tokens": max_tokens},
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = dispatch(tag_image, image_id, tag_prompt=tag_prompt, provider=provider, model=model, temperature=temperature, max_tokens_override=max_tokens, job_id=job.id, user_id=current_user.id)
    job.celery_task_id = task.id
    db.commit()

    return StepResponse(status="queued", image_id=image_id, step="tag", job_id=job.id)


@router.post("/{image_id}/describe", response_model=StepResponse)
async def describe_image_endpoint(
    image_id: int,
    request: DescribeRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate caption and description for an image."""
    image_service = get_image_service(db, current_user.id)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if image.status not in DESCRIBE_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Image status '{image.status}' does not allow describing")

    description_prompt = request.description_prompt if request else None
    provider = request.provider if request else None
    model = request.model if request else None
    temperature = request.temperature if request else None
    max_tokens = request.max_tokens if request else None

    job = Job(
        job_type=JobType.DESCRIBE,
        status=JobStatus.PENDING,
        image_id=image_id,
        total_items=1,
        parameters={"description_prompt": description_prompt, "provider": provider, "model": model, "temperature": temperature, "max_tokens": max_tokens},
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = dispatch(describe_image, image_id, description_prompt=description_prompt, provider=provider, model=model, temperature=temperature, max_tokens_override=max_tokens, job_id=job.id, user_id=current_user.id)
    job.celery_task_id = task.id
    db.commit()

    return StepResponse(status="queued", image_id=image_id, step="describe", job_id=job.id)


@router.post("/{image_id}/embed", response_model=StepResponse)
async def embed_image_endpoint(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate embedding for an image."""
    image_service = get_image_service(db, current_user.id)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if image.status not in EMBED_ALLOWED:
        raise HTTPException(status_code=400, detail=f"Image status '{image.status}' does not allow embedding")

    job = Job(
        job_type=JobType.EMBED,
        status=JobStatus.PENDING,
        image_id=image_id,
        total_items=1,
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = dispatch(embed_image, image_id, job_id=job.id, user_id=current_user.id)
    job.celery_task_id = task.id
    db.commit()

    return StepResponse(status="queued", image_id=image_id, step="embed", job_id=job.id)


# Thumbnail serving endpoint
@router.get("/thumbnails/{filename}")
async def get_thumbnail(filename: str, current_user: User = Depends(get_current_user_from_token_param)):
    """Serve thumbnail file."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    response = storage.get_file_response("thumbnails", filename, "image/jpeg")
    if response is None:
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    return response


# Full image serving endpoint
@router.get("/files/{filename}")
async def get_image_file(filename: str, current_user: User = Depends(get_current_user_from_token_param)):
    """Serve full image file."""
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    response = storage.get_file_response("images", filename)
    if response is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return response
