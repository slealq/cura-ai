"""Jobs API endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models import Image, ImageStatus, Job, JobStatus, JobType
from app.models.generated_image import GeneratedImage, GenerationStatus
from app.models.user import User
from app.schemas import BatchJobImageInfo, BatchReprocessRequest, JobListResponse, JobResponse
from app.workers.dispatch import dispatch
from app.workers.tasks import (
    cluster_all_images,
    describe_image,
    embed_image,
    process_image_pipeline,
    run_batch_reprocess,
    run_full_pipeline,
    tag_image,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


def _check_no_active_batch(db: Session) -> None:
    """Raise 409 if a BATCH_REPROCESS job is already RUNNING or PENDING."""
    active = (
        db.query(Job)
        .filter(
            Job.job_type == JobType.BATCH_REPROCESS,
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .first()
    )
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"A batch reprocess job is already active (job #{active.id}, status: {active.status.value}). "
                   "Cancel it first or wait for it to finish.",
        )


def _job_to_response(job: Job) -> JobResponse:
    """Convert Job model to response, populating image fields from relationship."""
    resp = JobResponse.model_validate(job)
    if job.image:
        resp.image_filename = job.image.original_filename
        # Extract just the filename from the full path for the thumbnail URL
        thumb = job.image.thumbnail_uri_small
        if thumb:
            resp.image_thumbnail = thumb.rsplit("/", 1)[-1]
    return resp


@router.get("", response_model=JobListResponse)
async def list_jobs(
    job_type: JobType | None = None,
    status: JobStatus | None = None,
    image_id: int | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List processing jobs with optional filters."""
    query = db.query(Job).filter(Job.user_id == current_user.id)

    if job_type:
        query = query.filter(Job.job_type == job_type)
    if status:
        query = query.filter(Job.status == status)
    if image_id:
        query = query.filter(Job.image_id == image_id)

    total = query.count()
    jobs = query.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()

    return JobListResponse(
        items=[_job_to_response(job) for job in jobs],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get job details by ID."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _job_to_response(job)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Cancel a running or pending job."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")

    # Revoke Celery task (prevents re-delivery of pending tasks).
    # For running generation tasks, the actual cancellation happens via
    # the cancel_check callback that polls Job.status in the DB.
    if job.celery_task_id:
        from app.workers.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id)

    job.status = JobStatus.CANCELLED

    # Clean up associated generated images that are still pending/generating
    if job.job_type in (JobType.GENERATE_IMAGE, JobType.BATCH_GENERATE):
        db.query(GeneratedImage).filter(
            GeneratedImage.job_id == job_id,
            GeneratedImage.status.in_([GenerationStatus.PENDING, GenerationStatus.GENERATING]),
        ).update(
            {
                GeneratedImage.status: GenerationStatus.FAILED,
                GeneratedImage.error_message: "Cancelled by user",
            },
            synchronize_session="fetch",
        )

    db.commit()

    return {"status": "cancelled", "job_id": job_id}


@router.post("/pipeline/full")
async def trigger_full_pipeline(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Trigger the full processing pipeline.

    This will:
    1. Process all pending/ingested images (tag, describe, embed)
    2. Note: Clustering should be triggered separately after processing completes
    """
    # Create job record
    job = Job(
        job_type=JobType.FULL_PIPELINE,
        status=JobStatus.PENDING,
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue task
    task = dispatch(run_full_pipeline, job.id, current_user.id)

    # Update job with task ID
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "job_id": job.id,
        "message": "Full pipeline job queued. Trigger clustering separately after processing completes.",
    }


@router.post("/pipeline/tag")
async def trigger_batch_tag(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Tag all ingested images."""
    images = db.query(Image).filter(Image.status == ImageStatus.INGESTED, Image.user_id == current_user.id).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No images ready for tagging"}

    job = Job(job_type=JobType.TAG, status=JobStatus.PENDING, total_items=len(images), user_id=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    for img in images:
        dispatch(tag_image, img.id, user_id=current_user.id)

    return {"status": "queued", "job_id": job.id, "total": len(images), "message": f"Tagging {len(images)} images"}


@router.post("/pipeline/describe")
async def trigger_batch_describe(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Describe all tagged images."""
    images = db.query(Image).filter(Image.status == ImageStatus.TAGGED, Image.user_id == current_user.id).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No images ready for describing"}

    job = Job(job_type=JobType.DESCRIBE, status=JobStatus.PENDING, total_items=len(images), user_id=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    for img in images:
        dispatch(describe_image, img.id, user_id=current_user.id)

    return {"status": "queued", "job_id": job.id, "total": len(images), "message": f"Describing {len(images)} images"}


@router.post("/pipeline/embed")
async def trigger_batch_embed(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Embed all described images."""
    images = db.query(Image).filter(Image.status == ImageStatus.DESCRIBED, Image.user_id == current_user.id).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No images ready for embedding"}

    job = Job(job_type=JobType.EMBED, status=JobStatus.PENDING, total_items=len(images), user_id=current_user.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    for img in images:
        dispatch(embed_image, img.id, user_id=current_user.id)

    return {"status": "queued", "job_id": job.id, "total": len(images), "message": f"Embedding {len(images)} images"}


@router.post("/pipeline/reprocess-all")
async def trigger_reprocess_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reprocess ALL images from scratch."""
    _check_no_active_batch(db)
    images = db.query(Image).filter(Image.user_id == current_user.id).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No images to reprocess"}

    image_ids = [img.id for img in images]

    job = Job(
        job_type=JobType.BATCH_REPROCESS,
        status=JobStatus.PENDING,
        total_items=len(image_ids),
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = dispatch(run_batch_reprocess, job.id, current_user.id, image_ids)
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "job_id": job.id,
        "total": len(image_ids),
        "message": f"Reprocessing all {len(image_ids)} images",
    }


@router.post("/pipeline/reprocess-failed")
async def trigger_reprocess_failed(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reprocess only FAILED images."""
    _check_no_active_batch(db)
    images = db.query(Image).filter(Image.status == ImageStatus.FAILED, Image.user_id == current_user.id).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No failed images to reprocess"}

    image_ids = [img.id for img in images]

    job = Job(
        job_type=JobType.BATCH_REPROCESS,
        status=JobStatus.PENDING,
        total_items=len(image_ids),
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = dispatch(run_batch_reprocess, job.id, current_user.id, image_ids)
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "job_id": job.id,
        "total": len(image_ids),
        "message": f"Reprocessing {len(image_ids)} failed images",
    }


@router.post("/pipeline/reprocess-selected")
async def trigger_reprocess_selected(
    request: BatchReprocessRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Reprocess specific images by ID."""
    _check_no_active_batch(db)
    images = db.query(Image).filter(Image.id.in_(request.image_ids)).all()
    found_ids = {img.id for img in images}
    missing = set(request.image_ids) - found_ids

    if missing:
        raise HTTPException(status_code=404, detail=f"Images not found: {sorted(missing)}")

    image_ids = list(found_ids)

    job = Job(
        job_type=JobType.BATCH_REPROCESS,
        status=JobStatus.PENDING,
        total_items=len(image_ids),
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    task = dispatch(run_batch_reprocess, job.id, current_user.id, image_ids)
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "job_id": job.id,
        "total": len(image_ids),
        "message": f"Reprocessing {len(image_ids)} selected images",
    }


@router.get("/{job_id}/images", response_model=list[BatchJobImageInfo])
async def get_job_images(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get images belonging to a batch job."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    image_ids = (job.result or {}).get("image_ids", [])
    if not image_ids:
        return []

    images = db.query(Image).filter(Image.id.in_(image_ids)).all()

    result = []
    for img in images:
        thumb = img.thumbnail_uri_small
        if thumb:
            thumb = thumb.rsplit("/", 1)[-1]
        result.append(BatchJobImageInfo(
            id=img.id,
            original_filename=img.original_filename,
            thumbnail=thumb,
        ))

    return result


@router.post("/{job_id}/retry")
async def retry_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Retry a failed job by creating a new job and dispatching the appropriate task."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=400, detail="Only failed jobs can be retried")

    # Create new job record
    new_job = Job(
        job_type=job.job_type,
        status=JobStatus.PENDING,
        image_id=job.image_id,
        total_items=job.total_items,
        parameters=job.parameters or {},
        user_id=current_user.id,
    )
    db.add(new_job)
    db.commit()
    db.refresh(new_job)

    user_id = current_user.id

    # Dispatch the appropriate Celery task
    if job.job_type == JobType.TAG and job.image_id:
        task = dispatch(tag_image, job.image_id, user_id, job_id=new_job.id)
    elif job.job_type == JobType.DESCRIBE and job.image_id:
        task = dispatch(describe_image, job.image_id, user_id, job_id=new_job.id)
    elif job.job_type == JobType.EMBED and job.image_id:
        task = dispatch(embed_image, job.image_id, user_id, job_id=new_job.id)
    elif job.job_type == JobType.FULL_PIPELINE and job.image_id:
        task = dispatch(process_image_pipeline, job.image_id, user_id, job_id=new_job.id)
    elif job.job_type == JobType.CLUSTER:
        task = dispatch(cluster_all_images, user_id, job_id=new_job.id)
    elif job.job_type == JobType.BATCH_REPROCESS:
        image_ids = (job.result or {}).get("image_ids", [])
        if not image_ids:
            db.delete(new_job)
            db.commit()
            raise HTTPException(status_code=400, detail="No image IDs found in original job to retry")
        task = dispatch(run_batch_reprocess, new_job.id, user_id, image_ids)
    elif job.job_type == JobType.GENERATE_IMAGE:
        from app.workers.generation_tasks import generate_image
        params = job.parameters or {}
        generated_image_id = params.get("generated_image_id")
        if not generated_image_id:
            db.delete(new_job)
            db.commit()
            raise HTTPException(status_code=400, detail="No generated_image_id in original job parameters")
        # Reset generated image status
        gen = db.query(GeneratedImage).filter(GeneratedImage.id == generated_image_id).first()
        if gen:
            gen.status = GenerationStatus.PENDING
            gen.error_message = None
            db.commit()
        task = dispatch(generate_image, generated_image_id, job_id=new_job.id, user_id=user_id)
    elif job.job_type == JobType.BATCH_GENERATE:
        from app.workers.generation_tasks import batch_generate
        params = job.parameters or {}
        generated_image_ids = params.get("generated_image_ids", [])
        if not generated_image_ids:
            # Try result field
            generated_image_ids = (job.result or {}).get("generated_image_ids", [])
        if not generated_image_ids:
            db.delete(new_job)
            db.commit()
            raise HTTPException(status_code=400, detail="No generated_image_ids found to retry")
        # Reset generated images
        db.query(GeneratedImage).filter(
            GeneratedImage.id.in_(generated_image_ids),
        ).update(
            {GeneratedImage.status: GenerationStatus.PENDING, GeneratedImage.error_message: None},
            synchronize_session="fetch",
        )
        db.commit()
        task = dispatch(batch_generate, generated_image_ids, job_id=new_job.id, user_id=user_id)
    elif job.job_type == JobType.LORA_EVALUATE:
        from app.workers.generation_tasks import evaluate_lora
        params = job.parameters or {}
        evaluation_id = params.get("evaluation_id")
        if not evaluation_id:
            db.delete(new_job)
            db.commit()
            raise HTTPException(status_code=400, detail="No evaluation_id in original job parameters")
        task = dispatch(evaluate_lora, evaluation_id, job_id=new_job.id, user_id=user_id)
    elif job.job_type == JobType.LORA_TRAIN:
        # LoRA training has its own retry via /generation/lora/{id}/retry
        db.delete(new_job)
        db.commit()
        raise HTTPException(status_code=400, detail="Use the LoRA-specific retry endpoint for training jobs")
    else:
        db.delete(new_job)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Retry not supported for job type: {job.job_type.value}")

    new_job.celery_task_id = task.id
    db.commit()

    return {"status": "queued", "job_id": new_job.id}


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a job record."""
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cannot delete running job")

    db.delete(job)
    db.commit()

    return {"status": "deleted", "job_id": job_id}
