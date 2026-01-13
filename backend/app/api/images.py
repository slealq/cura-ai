"""Image API endpoints."""
import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import get_db
from app.models import ImageSource, ImageStatus, Job, JobStatus, JobType
from app.schemas import (
    BatchUploadResponse,
    ImageListResponse,
    ImageResponse,
    PipelineStats,
    UploadResponse,
)
from app.services.image_service import get_image_service
from app.workers.tasks import process_image_pipeline

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/images", tags=["images"])


@router.post("/upload", response_model=UploadResponse)
async def upload_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a single image for processing."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    image_service = get_image_service(db)

    try:
        file_data = await file.read()
        image = await image_service.ingest_image(
            file_data=file_data,
            filename=file.filename or "upload.jpg",
            source=ImageSource.UPLOAD,
        )

        # Queue for processing
        process_image_pipeline.delay(image.id)

        return UploadResponse(
            image_id=image.id,
            filename=file.filename or "upload.jpg",
            status="queued",
            message="Image uploaded and queued for processing",
        )
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/batch", response_model=BatchUploadResponse)
async def upload_images_batch(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """Upload multiple images for processing."""
    image_service = get_image_service(db)
    uploaded = []
    failed = []

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
            )

            # Queue for processing
            process_image_pipeline.delay(image.id)

            uploaded.append(
                UploadResponse(
                    image_id=image.id,
                    filename=file.filename or "upload.jpg",
                    status="queued",
                    message="Image uploaded and queued for processing",
                )
            )
        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            failed.append({"filename": file.filename, "error": str(e)})

    return BatchUploadResponse(uploaded=uploaded, failed=failed)


@router.get("", response_model=ImageListResponse)
async def list_images(
    status: ImageStatus | None = None,
    source: ImageSource | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List images with optional filtering."""
    image_service = get_image_service(db)
    images = image_service.get_images(
        status=status,
        source=source,
        skip=skip,
        limit=limit,
    )
    total = image_service.count_images(status=status)

    return ImageListResponse(
        items=[ImageResponse.model_validate(img) for img in images],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/stats", response_model=PipelineStats)
async def get_pipeline_stats(db: Session = Depends(get_db)):
    """Get pipeline processing statistics."""
    image_service = get_image_service(db)
    from app.services.cluster_service import get_cluster_service
    cluster_service = get_cluster_service(db)

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
async def get_image(image_id: int, db: Session = Depends(get_db)):
    """Get image by ID."""
    image_service = get_image_service(db)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    return ImageResponse.model_validate(image)


@router.delete("/{image_id}")
async def delete_image(image_id: int, db: Session = Depends(get_db)):
    """Delete an image."""
    image_service = get_image_service(db)

    if not image_service.delete_image(image_id):
        raise HTTPException(status_code=404, detail="Image not found")

    return {"status": "deleted", "image_id": image_id}


@router.get("/{image_id}/similar", response_model=list[ImageResponse])
async def get_similar_images(
    image_id: int,
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Get images similar to the specified image based on embeddings."""
    from sqlalchemy import text

    image_service = get_image_service(db)
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
        AND m.embedding IS NOT NULL
        ORDER BY m.embedding <-> :embedding
        LIMIT :limit
    """)

    result = db.execute(
        query,
        {"image_id": image_id, "embedding": embedding_str, "limit": limit}
    )
    similar_ids = [row[0] for row in result]

    similar_images = image_service.get_images_by_ids(similar_ids)

    return [ImageResponse.model_validate(img) for img in similar_images]


@router.post("/{image_id}/reprocess")
async def reprocess_image(image_id: int, db: Session = Depends(get_db)):
    """Reprocess an image through the pipeline."""
    image_service = get_image_service(db)
    image = image_service.get_image(image_id)

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Reset status and queue for reprocessing
    image_service.update_status(image_id, ImageStatus.INGESTED)
    process_image_pipeline.delay(image_id)

    return {"status": "queued", "image_id": image_id, "message": "Image queued for reprocessing"}


# Thumbnail serving endpoint
@router.get("/thumbnails/{filename}")
async def get_thumbnail(filename: str):
    """Serve thumbnail file."""
    thumbnail_path = Path(settings.local_storage_path) / "thumbnails" / filename

    if not thumbnail_path.exists():
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    return FileResponse(thumbnail_path, media_type="image/jpeg")


# Full image serving endpoint
@router.get("/files/{filename}")
async def get_image_file(filename: str):
    """Serve full image file."""
    image_path = Path(settings.local_storage_path) / "images" / filename

    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    return FileResponse(image_path)
