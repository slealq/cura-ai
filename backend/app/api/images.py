"""Image API endpoints."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_user, get_current_user_from_token_param
from app.db.base import get_db
from app.models import ImageSource, ImageStatus, Job, JobStatus, JobType
from app.models.user import User
from app.schemas import (
    BatchUploadResponse,
    ImageListResponse,
    ImageResponse,
    PipelineStats,
    StepResponse,
    UploadResponse,
)
from app.services.folder_service import get_folder_service
from app.services.image_service import get_image_service
from app.workers.tasks import (
    describe_image,
    embed_image,
    process_image_pipeline,
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
    job_id: int | None = Query(None),
    total_items: int | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Upload multiple images for processing."""
    image_service = get_image_service(db, current_user.id)

    # Create or load the INGEST job for tracking
    if job_id is not None:
        job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
    else:
        job = Job(
            job_type=JobType.INGEST,
            status=JobStatus.RUNNING,
            total_items=total_items or len(files),
            progress=0,
            user_id=current_user.id,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

    uploaded = []
    failed = []
    uploaded_image_ids = []

    for file in files:
        if not file.content_type or not file.content_type.startswith("image/"):
            failed.append({"filename": file.filename, "error": "Not an image file"})
            continue

        try:
            file_data = await file.read()
            image = await image_service.ingest_image(
                file_data=file_data,
                filename=file.filename or "upload.jpg",
                source=ImageSource.UPLOAD,
                job_id=job.id,
            )

            uploaded.append(
                UploadResponse(
                    image_id=image.id,
                    filename=file.filename or "upload.jpg",
                    status="ingested",
                    message="Image uploaded successfully",
                )
            )
            uploaded_image_ids.append(image.id)
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            failed.append({"filename": file.filename, "error": str(e)})

        # Update job progress after each file (success or fail)
        job.progress = (job.progress or 0) + 1
        db.commit()

    # Mark job completed if all items have been processed
    if job.progress >= job.total_items:
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        db.commit()

    folder_error = None
    if folder_id and uploaded_image_ids:
        try:
            folder_service = get_folder_service(db, current_user.id)
            folder_service.add_images_to_folder(folder_id, uploaded_image_ids)
        except Exception as e:
            logger.error(f"Failed to add {len(uploaded_image_ids)} images to folder {folder_id}: {e}")
            folder_error = str(e)

    return BatchUploadResponse(
        uploaded=uploaded,
        failed=failed,
        job_id=job.id,
        folder_error=folder_error,
    )


@router.get("", response_model=ImageListResponse)
async def list_images(
    status: ImageStatus | None = None,
    min_status: ImageStatus | None = None,
    source: ImageSource | None = None,
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
        source=source,
        skip=skip,
        limit=limit,
    )
    total = image_service.count_images(status=status, min_status=min_status)

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

    if not image.image_metadata or not image.image_metadata.embedding:
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

    # Create job record
    job = Job(
        job_type=JobType.REPROCESS,
        status=JobStatus.PENDING,
        image_id=image_id,
        total_items=1,
        parameters={"tag_prompt": tag_prompt, "description_prompt": description_prompt},
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Reset status and queue for reprocessing
    image_service.update_status(image_id, ImageStatus.INGESTED)
    task = process_image_pipeline.delay(image_id, tag_prompt=tag_prompt, description_prompt=description_prompt, job_id=job.id, user_id=current_user.id)
    job.celery_task_id = task.id
    db.commit()

    return StepResponse(status="queued", image_id=image_id, step="reprocess", job_id=job.id)


class TagRequest(BaseModel):
    """Request to tag an image."""

    tag_prompt: str | None = None


class DescribeRequest(BaseModel):
    """Request to describe an image."""

    description_prompt: str | None = None


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

    job = Job(
        job_type=JobType.TAG,
        status=JobStatus.PENDING,
        image_id=image_id,
        total_items=1,
        parameters={"tag_prompt": tag_prompt} if tag_prompt else {},
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = tag_image.delay(image_id, tag_prompt=tag_prompt, job_id=job.id, user_id=current_user.id)
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

    job = Job(
        job_type=JobType.DESCRIBE,
        status=JobStatus.PENDING,
        image_id=image_id,
        total_items=1,
        parameters={"description_prompt": description_prompt} if description_prompt else {},
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = describe_image.delay(image_id, description_prompt=description_prompt, job_id=job.id, user_id=current_user.id)
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

    task = embed_image.delay(image_id, job_id=job.id, user_id=current_user.id)
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
