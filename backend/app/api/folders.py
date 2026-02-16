"""Folders API endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user, get_current_user_from_token_param
from app.db.base import get_db
from app.models import ImageStatus, Job, JobStatus, JobType
from app.models.folder import Folder
from app.models.user import User
from app.schemas import ImageListResponse, ImageResponse
from app.services.folder_service import get_folder_service
from app.services.storage import get_storage_service
from app.workers.tasks import delete_folder_with_images, run_batch_reprocess

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/folders", tags=["folders"])


# --- Schemas ---

class FolderCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    description: str | None = None


class FolderUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=256)
    description: str | None = None


class FolderImageIdsRequest(BaseModel):
    image_ids: list[int] = Field(..., min_length=1)


class FolderPreviewImage(BaseModel):
    id: int
    thumbnail_uri_small: str | None
    thumbnail_uri_medium: str | None

    class Config:
        from_attributes = True


class FolderResponse(BaseModel):
    id: int
    name: str
    description: str | None
    image_count: int
    cover_thumbnail_url: str | None = None
    created_at: str
    updated_at: str
    preview_images: list[FolderPreviewImage] = Field(default_factory=list)

    class Config:
        from_attributes = True


class FolderListResponse(BaseModel):
    items: list[FolderResponse]
    total: int
    skip: int
    limit: int


class FolderBriefResponse(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


# --- Routes ---

@router.post("", response_model=FolderResponse)
async def create_folder(request: FolderCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    folder_service = get_folder_service(db, current_user.id)
    folder = folder_service.create_folder(name=request.name, description=request.description)
    return _folder_to_response(folder, [])


@router.get("", response_model=FolderListResponse)
async def list_folders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder_service = get_folder_service(db, current_user.id)
    folders = folder_service.get_folders(skip=skip, limit=limit)
    total = folder_service.count_folders()

    storage = get_storage_service()
    items = []
    for folder in folders:
        cover_url = storage.generate_folder_cover_sas_url(folder.cover_thumbnail_uri)
        items.append(_folder_to_response(folder, [], cover_thumbnail_url=cover_url))

    return FolderListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/covers/{filename}")
async def serve_folder_cover(
    filename: str,
    current_user: User = Depends(get_current_user_from_token_param),
):
    """Serve a folder cover composite image (local storage only)."""
    storage = get_storage_service()
    response = storage.get_file_response("folder_covers", filename)
    if response is None:
        raise HTTPException(status_code=404, detail="Cover not found")
    return response


@router.post("/backfill-covers")
async def backfill_covers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate composite cover images for all existing folders."""
    folder_service = get_folder_service(db, current_user.id)
    folders = db.query(Folder).filter(Folder.user_id == current_user.id).all()
    generated = 0
    for folder in folders:
        try:
            folder_service.generate_cover_composite(folder.id)
            generated += 1
        except Exception as e:
            logger.warning(f"Failed to generate cover for folder {folder.id}: {e}")
    return {"status": "ok", "generated": generated, "total": len(folders)}


@router.get("/{folder_id}", response_model=FolderResponse)
async def get_folder(folder_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    folder_service = get_folder_service(db, current_user.id)
    folder = folder_service.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    previews = folder_service.get_folder_preview_images(folder_id, count=4)
    storage = get_storage_service()
    cover_url = storage.generate_folder_cover_sas_url(folder.cover_thumbnail_uri)
    return _folder_to_response(folder, previews, cover_thumbnail_url=cover_url)


@router.patch("/{folder_id}", response_model=FolderResponse)
async def update_folder(folder_id: int, request: FolderUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    folder_service = get_folder_service(db, current_user.id)
    folder = folder_service.update_folder(folder_id, name=request.name, description=request.description)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    previews = folder_service.get_folder_preview_images(folder_id, count=4)
    storage = get_storage_service()
    cover_url = storage.generate_folder_cover_sas_url(folder.cover_thumbnail_uri)
    return _folder_to_response(folder, previews, cover_thumbnail_url=cover_url)


@router.delete("/{folder_id}")
async def delete_folder(
    folder_id: int,
    delete_images: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder_service = get_folder_service(db, current_user.id)

    if delete_images:
        folder = folder_service.get_folder(folder_id)
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        image_count = folder_service.count_folder_images(folder_id)

        job = Job(
            job_type=JobType.FOLDER_DELETE,
            status=JobStatus.PENDING,
            total_items=image_count,
            user_id=current_user.id,
            parameters={"folder_id": folder_id, "folder_name": folder.name},
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        task = delete_folder_with_images.delay(folder_id, current_user.id, job.id)
        job.celery_task_id = task.id
        db.commit()

        return {
            "status": "queued",
            "job_id": job.id,
            "total": image_count,
            "message": f"Deleting folder '{folder.name}' and {image_count} image{'s' if image_count != 1 else ''}",
        }

    if not folder_service.delete_folder(folder_id):
        raise HTTPException(status_code=404, detail="Folder not found")
    return {"status": "deleted", "folder_id": folder_id}


@router.post("/{folder_id}/images")
async def add_images_to_folder(folder_id: int, request: FolderImageIdsRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    folder_service = get_folder_service(db, current_user.id)
    folder = folder_service.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    added = folder_service.add_images_to_folder(folder_id, request.image_ids)
    return {"added": added, "folder_id": folder_id}


@router.delete("/{folder_id}/images")
async def remove_images_from_folder(folder_id: int, request: FolderImageIdsRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    folder_service = get_folder_service(db, current_user.id)
    folder = folder_service.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    removed = folder_service.remove_images_from_folder(folder_id, request.image_ids)
    return {"removed": removed, "folder_id": folder_id}


@router.get("/{folder_id}/images", response_model=ImageListResponse)
async def list_folder_images(
    folder_id: int,
    status: ImageStatus | None = None,
    min_status: ImageStatus | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    folder_service = get_folder_service(db, current_user.id)
    folder = folder_service.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    images = folder_service.get_folder_images(
        folder_id, status=status, min_status=min_status, skip=skip, limit=limit
    )
    total = folder_service.count_folder_images(folder_id, status=status, min_status=min_status)
    return ImageListResponse(
        items=[ImageResponse.model_validate(img) for img in images],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.post("/{folder_id}/reprocess")
async def reprocess_folder(folder_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    folder_service = get_folder_service(db, current_user.id)
    folder = folder_service.get_folder(folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")

    image_ids = folder_service.get_folder_image_ids(folder_id)
    if not image_ids:
        return {"status": "skipped", "total": 0, "message": "No images in folder"}

    job = Job(
        job_type=JobType.BATCH_REPROCESS,
        status=JobStatus.PENDING,
        total_items=len(image_ids),
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = run_batch_reprocess.delay(job.id, current_user.id, image_ids)
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "job_id": job.id,
        "total": len(image_ids),
        "message": f"Reprocessing {len(image_ids)} images from folder '{folder.name}'",
    }


def _folder_to_response(
    folder, preview_images, cover_thumbnail_url: str | None = None,
) -> FolderResponse:
    previews = [
        FolderPreviewImage(
            id=img.id,
            thumbnail_uri_small=img.thumbnail_uri_small,
            thumbnail_uri_medium=img.thumbnail_uri_medium,
        )
        for img in preview_images
    ]
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        description=folder.description,
        image_count=folder.image_count,
        cover_thumbnail_url=cover_thumbnail_url,
        created_at=folder.created_at.isoformat(),
        updated_at=folder.updated_at.isoformat(),
        preview_images=previews,
    )
