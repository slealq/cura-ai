"""Jobs API endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models import Image, ImageStatus, Job, JobStatus, JobType
from app.schemas import JobListResponse, JobResponse
from app.workers.tasks import describe_image, embed_image, run_full_pipeline, tag_image

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/jobs", tags=["jobs"])


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
):
    """List processing jobs with optional filters."""
    query = db.query(Job)

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
async def get_job(job_id: int, db: Session = Depends(get_db)):
    """Get job details by ID."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _job_to_response(job)


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Cancel a running or pending job."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
        raise HTTPException(status_code=400, detail="Job cannot be cancelled")

    # Cancel Celery task if possible
    if job.celery_task_id:
        from app.workers.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)

    job.status = JobStatus.CANCELLED
    db.commit()

    return {"status": "cancelled", "job_id": job_id}


@router.post("/pipeline/full")
async def trigger_full_pipeline(db: Session = Depends(get_db)):
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
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue task
    task = run_full_pipeline.delay(job.id)

    # Update job with task ID
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "job_id": job.id,
        "message": "Full pipeline job queued. Trigger clustering separately after processing completes.",
    }


@router.post("/pipeline/tag")
async def trigger_batch_tag(db: Session = Depends(get_db)):
    """Tag all ingested images."""
    images = db.query(Image).filter(Image.status == ImageStatus.INGESTED).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No images ready for tagging"}

    job = Job(job_type=JobType.TAG, status=JobStatus.PENDING, total_items=len(images))
    db.add(job)
    db.commit()
    db.refresh(job)

    for img in images:
        tag_image.delay(img.id)

    return {"status": "queued", "job_id": job.id, "total": len(images), "message": f"Tagging {len(images)} images"}


@router.post("/pipeline/describe")
async def trigger_batch_describe(db: Session = Depends(get_db)):
    """Describe all tagged images."""
    images = db.query(Image).filter(Image.status == ImageStatus.TAGGED).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No images ready for describing"}

    job = Job(job_type=JobType.DESCRIBE, status=JobStatus.PENDING, total_items=len(images))
    db.add(job)
    db.commit()
    db.refresh(job)

    for img in images:
        describe_image.delay(img.id)

    return {"status": "queued", "job_id": job.id, "total": len(images), "message": f"Describing {len(images)} images"}


@router.post("/pipeline/embed")
async def trigger_batch_embed(db: Session = Depends(get_db)):
    """Embed all described images."""
    images = db.query(Image).filter(Image.status == ImageStatus.DESCRIBED).all()

    if not images:
        return {"status": "skipped", "total": 0, "message": "No images ready for embedding"}

    job = Job(job_type=JobType.EMBED, status=JobStatus.PENDING, total_items=len(images))
    db.add(job)
    db.commit()
    db.refresh(job)

    for img in images:
        embed_image.delay(img.id)

    return {"status": "queued", "job_id": job.id, "total": len(images), "message": f"Embedding {len(images)} images"}


@router.delete("/{job_id}")
async def delete_job(job_id: int, db: Session = Depends(get_db)):
    """Delete a job record."""
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.RUNNING:
        raise HTTPException(status_code=400, detail="Cannot delete running job")

    db.delete(job)
    db.commit()

    return {"status": "deleted", "job_id": job_id}
