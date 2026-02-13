"""Cluster API endpoints."""
import io
import logging
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_user
from app.db.base import get_db
from app.models.user import User
from app.models import Job, JobStatus, JobType
from app.schemas import (
    ClusterDetailResponse,
    ClusterListResponse,
    ClusterMergeRequest,
    ClusterRenameRequest,
    ClusterResponse,
    ImageResponse,
    TriggerClusteringRequest,
    TriggerClusteringResponse,
)
from app.services.cluster_service import get_cluster_service
from app.workers.tasks import cluster_all_images, summarize_cluster, summarize_clusters

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.get("", response_model=ClusterListResponse)
async def list_clusters(
    include_archived: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all clusters from the latest clustering run."""
    cluster_service = get_cluster_service(db, current_user.id)
    clusters = cluster_service.get_latest_clusters(limit=limit)

    if not include_archived:
        clusters = [c for c in clusters if not c.is_archived]

    return ClusterListResponse(
        items=[ClusterResponse.model_validate(c) for c in clusters],
        total=len(clusters),
        skip=skip,
        limit=limit,
    )


@router.get("/{cluster_id}", response_model=ClusterDetailResponse)
async def get_cluster(cluster_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get cluster details with images."""
    cluster_service = get_cluster_service(db, current_user.id)
    cluster = cluster_service.get_cluster(cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    images = cluster_service.get_cluster_images(cluster_id, limit=cluster.size or 10000)

    response = ClusterDetailResponse.model_validate(cluster)
    response.images = [ImageResponse.model_validate(img) for img in images]

    return response


@router.get("/{cluster_id}/images", response_model=list[ImageResponse])
async def get_cluster_images(
    cluster_id: int,
    include_outliers: bool = True,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get paginated images in a cluster."""
    cluster_service = get_cluster_service(db, current_user.id)
    images = cluster_service.get_cluster_images(
        cluster_id,
        include_outliers=include_outliers,
        skip=skip,
        limit=limit,
    )

    return [ImageResponse.model_validate(img) for img in images]


@router.patch("/{cluster_id}/rename", response_model=ClusterResponse)
async def rename_cluster(
    cluster_id: int,
    request: ClusterRenameRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Rename a cluster."""
    cluster_service = get_cluster_service(db, current_user.id)
    cluster = cluster_service.rename_cluster(cluster_id, request.display_name)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return ClusterResponse.model_validate(cluster)


@router.post("/{cluster_id}/pin", response_model=ClusterResponse)
async def toggle_pin_cluster(cluster_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Toggle pinned status of a cluster."""
    cluster_service = get_cluster_service(db, current_user.id)
    cluster = cluster_service.toggle_pin(cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return ClusterResponse.model_validate(cluster)


@router.post("/{cluster_id}/archive", response_model=ClusterResponse)
async def archive_cluster(cluster_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Archive a cluster."""
    cluster_service = get_cluster_service(db, current_user.id)
    cluster = cluster_service.archive_cluster(cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    return ClusterResponse.model_validate(cluster)


@router.post("/merge", response_model=ClusterResponse)
async def merge_clusters(request: ClusterMergeRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Merge multiple clusters into one."""
    cluster_service = get_cluster_service(db, current_user.id)

    try:
        merged = cluster_service.merge_clusters(
            request.cluster_ids,
            new_name=request.new_name,
        )
        return ClusterResponse.model_validate(merged)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{cluster_id}/images/{image_id}")
async def exclude_image_from_cluster(
    cluster_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Exclude an image from a cluster (mark as outlier)."""
    cluster_service = get_cluster_service(db, current_user.id)

    if not cluster_service.exclude_image_from_cluster(cluster_id, image_id):
        raise HTTPException(status_code=404, detail="Membership not found")

    return {"status": "excluded", "cluster_id": cluster_id, "image_id": image_id}


@router.post("/{cluster_id}/summarize")
async def trigger_cluster_summarization(
    cluster_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger AI summarization for a specific cluster."""
    cluster_service = get_cluster_service(db, current_user.id)
    cluster = cluster_service.get_cluster(cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    # Queue summarization task
    summarize_cluster.delay(cluster_id, current_user.id)

    return {"status": "queued", "cluster_id": cluster_id, "message": "Summarization queued"}


@router.post("/recluster", response_model=TriggerClusteringResponse)
async def trigger_reclustering(
    request: TriggerClusteringRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger re-clustering of all embedded images."""
    # Create job record
    job = Job(
        job_type=JobType.CLUSTER,
        status=JobStatus.PENDING,
        parameters={"method": request.method if request else None},
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue clustering task
    task = cluster_all_images.delay(job.id, current_user.id)

    # Update job with task ID
    job.celery_task_id = task.id
    db.commit()

    return TriggerClusteringResponse(
        job_id=job.id,
        status="queued",
        message="Clustering job queued",
    )


@router.post("/summarize-all")
async def trigger_all_cluster_summarization(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Trigger AI summarization for all clusters."""
    cluster_service = get_cluster_service(db, current_user.id)
    clusters = cluster_service.get_latest_clusters(limit=500)
    cluster_ids = [c.id for c in clusters if not c.summary_title]

    if not cluster_ids:
        return {"status": "skipped", "message": "All clusters already have summaries"}

    # Create job
    job = Job(
        job_type=JobType.SUMMARIZE_CLUSTER,
        status=JobStatus.PENDING,
        total_items=len(cluster_ids),
        user_id=current_user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue task
    task = summarize_clusters.delay(cluster_ids, job.id, current_user.id)
    job.celery_task_id = task.id
    db.commit()

    return {
        "status": "queued",
        "job_id": job.id,
        "clusters_to_summarize": len(cluster_ids),
    }


@router.get("/{cluster_id}/export")
async def export_cluster(
    cluster_id: int,
    format: str = Query("json", regex="^(json|zip)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export cluster data as JSON or ZIP (with images)."""
    cluster_service = get_cluster_service(db, current_user.id)
    cluster = cluster_service.get_cluster(cluster_id)

    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")

    images = cluster_service.get_cluster_images(cluster_id, limit=cluster.size or 10000)

    if format == "json":
        export_data = {
            "cluster": ClusterResponse.model_validate(cluster).model_dump(),
            "images": [ImageResponse.model_validate(img).model_dump() for img in images],
        }

        import json
        return StreamingResponse(
            io.BytesIO(json.dumps(export_data, indent=2, default=str).encode()),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="cluster_{cluster_id}.json"'
            },
        )

    elif format == "zip":
        # Create ZIP with images
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # Add metadata
            import json
            metadata = {
                "cluster": ClusterResponse.model_validate(cluster).model_dump(),
                "images": [ImageResponse.model_validate(img).model_dump() for img in images],
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2, default=str))

            # Add images
            storage_path = Path(settings.local_storage_path) / "images"
            for img in images:
                img_path = storage_path / img.object_key
                if img_path.exists():
                    zf.write(img_path, f"images/{img.original_filename or img.object_key}")

        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="cluster_{cluster_id}.zip"'
            },
        )
