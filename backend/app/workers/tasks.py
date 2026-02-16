"""Celery tasks for the image processing pipeline."""
import asyncio
import logging
import time
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import Image, ImageStatus, Job, JobStatus
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers import get_cluster_summarizer, get_describer, get_embedder, get_tagger
from app.services.cluster_service import get_cluster_service
from app.services.clustering import get_clustering_service
from app.services.image_service import get_image_service
from app.services.log_service import write_log
from app.services.settings_service import (
    compose_description_prompt,
    compose_tag_prompt,
    get_settings_service,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _unwrap_error(e: Exception) -> str:
    """Extract a readable error message, unwrapping RetryError if needed."""
    # tenacity wraps the real exception in RetryError
    if hasattr(e, 'last_attempt'):
        try:
            e.last_attempt.result()
        except Exception as inner:
            return str(inner)
    return str(e)


def get_db() -> Session:
    """Get database session for worker."""
    return SessionLocal()


def run_async(coro):
    """Run async function in sync context (works in thread-pool workers)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread — create one
        return asyncio.run(coro)
    # Nested async — create a separate loop
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    finally:
        new_loop.close()


def _update_job_status(db: Session, job_id: int | None, status: JobStatus, **kwargs):
    """Helper to update job status fields."""
    if not job_id:
        return
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return
    job.status = status
    if status == JobStatus.RUNNING:
        job.started_at = datetime.utcnow()
    elif status in (JobStatus.COMPLETED, JobStatus.FAILED):
        job.completed_at = datetime.utcnow()
    for key, value in kwargs.items():
        setattr(job, key, value)
    db.commit()


def _assign_folder_on_completion(db: Session, job: Job):
    """Create folder (if needed) and assign images when an ingest job completes.

    Reads folder_id / new_folder_name from job.parameters and all_upload_ids
    from job.result. This ensures folders only appear in the UI once all
    images have thumbnails generated.
    """
    params = job.parameters or {}
    folder_id = params.get("folder_id")
    new_folder_name = params.get("new_folder_name")
    all_upload_ids = (job.result or {}).get("all_upload_ids", [])

    if not (folder_id or new_folder_name) or not all_upload_ids:
        return

    try:
        from app.services.folder_service import get_folder_service
        folder_service = get_folder_service(db, job.user_id)

        if new_folder_name:
            folder = folder_service.create_folder(new_folder_name)
            folder_id = folder.id

        if folder_id:
            folder_service.add_images_to_folder(folder_id, all_upload_ids)
            folder_service.refresh_cover_image(folder_id)
            folder_service.generate_cover_composite(folder_id)
            logger.info(f"Deferred folder assignment: added {len(all_upload_ids)} images to folder {folder_id} for job {job.id}")
    except Exception as e:
        logger.error(f"Failed deferred folder assignment for job {job.id}: {e}")


def _finish_ingest_job_item(db: Session, job_id: int | None, *, failed: bool):
    """Increment job progress and finalize when all items are done.

    When the last item finishes, counts actual FAILED images to set the
    correct job status (FAILED if all failed, COMPLETED otherwise).
    Then runs deferred folder assignment if configured.
    """
    if not job_id:
        return
    try:
        db.execute(
            Job.__table__.update()
            .where(Job.id == job_id)
            .values(progress=Job.progress + 1)
        )
        db.commit()

        job = db.query(Job).filter(Job.id == job_id).first()
        if job and job.total_items and job.progress >= job.total_items:
            # Count how many images from this job actually failed
            image_ids = (job.result or {}).get("image_ids", [])
            n_failed = 0
            if image_ids:
                n_failed = (
                    db.query(Image)
                    .filter(Image.id.in_(image_ids), Image.status == ImageStatus.FAILED)
                    .count()
                )

            job.completed_at = datetime.utcnow()
            if n_failed >= job.total_items:
                job.status = JobStatus.FAILED
                job.error_message = f"All {n_failed} items failed"
            elif n_failed > 0:
                job.status = JobStatus.COMPLETED
                job.error_message = f"{n_failed}/{job.total_items} items failed"
            else:
                job.status = JobStatus.COMPLETED
            db.commit()

            # Deferred folder assignment — only after all images are ingested
            _assign_folder_on_completion(db, job)
    except Exception:
        pass


@celery_app.task(bind=True)
def process_ingest(self, image_id: int, user_id: int, job_id: int | None = None) -> dict:
    """
    Complete the heavy processing for a fast-ingested image.

    Reads the raw file back from storage, detects MIME type, gets dimensions,
    generates 3 thumbnails, computes perceptual hash, and updates the Image
    record to INGESTED status. Atomically increments Job progress.
    """
    write_log(category=LogCategory.TASK, message=f"Task process_ingest started for image {image_id}",
              task_name="process_ingest", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        image_service = get_image_service(db, user_id)
        storage = image_service.storage
        image = image_service.get_image(image_id)

        if not image:
            logger.error(f"Image {image_id} not found")
            return {"status": "error", "message": "Image not found"}

        # Read file back from storage
        file_data = run_async(storage.get_image(image.object_key))

        # Detect MIME type via PIL
        mime_type = storage.get_mime_type(file_data)

        # Get dimensions via PIL
        width, height = storage.get_image_dimensions(file_data)

        # Generate 3 thumbnails and save to storage
        thumbnails = run_async(storage.generate_thumbnails(file_data, image.object_key))

        # Compute perceptual hash
        perceptual_hash = storage.compute_perceptual_hash(file_data)

        # Update Image record
        image.mime_type = mime_type
        image.width = width
        image.height = height
        image.perceptual_hash = perceptual_hash
        image.thumbnail_uri_small = thumbnails.get("200")
        image.thumbnail_uri_medium = thumbnails.get("400")
        image.thumbnail_uri_large = thumbnails.get("800")
        image.status = ImageStatus.INGESTED
        image.ingested_at = datetime.utcnow()
        image.error_message = None
        db.commit()

        # Atomically increment Job progress
        _finish_ingest_job_item(db, job_id, failed=False)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task process_ingest completed for image {image_id} in {elapsed:.0f}ms ({width}x{height})",
                  task_name="process_ingest", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "image_id": image_id, "width": width, "height": height}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to process ingest for image {image_id}: {err_msg}")
        write_log(category=LogCategory.TASK,
                  message=f"Task process_ingest failed for image {image_id}: {err_msg}",
                  level=LogLevel.ERROR, task_name="process_ingest", image_id=image_id,
                  job_id=job_id, duration_ms=round(elapsed, 1),
                  extra={"error": err_msg}, user_id=user_id)
        # Mark image as FAILED
        try:
            image = db.query(Image).filter(Image.id == image_id).first()
            if image:
                image.status = ImageStatus.FAILED
                image.error_message = err_msg
                image.retry_count += 1
                db.commit()
        except Exception:
            pass
        # Still increment job progress on failure so the job can complete
        _finish_ingest_job_item(db, job_id, failed=True)
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def tag_image(self, image_id: int, user_id: int, tag_prompt: str | None = None, job_id: int | None = None) -> dict:
    """
    Tag an image with categorization tags.

    Pipeline stage: 3
    """
    write_log(category=LogCategory.TASK, message=f"Task tag_image started for image {image_id}",
              task_name="tag_image", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db, user_id)
        image = image_service.get_image(image_id)

        if not image:
            logger.error(f"Image {image_id} not found")
            return {"status": "error", "message": "Image not found"}

        # Get image data
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get composed prompt: settings default or wrap user-provided guidance
        if tag_prompt is None:
            settings_service = get_settings_service(db, user_id)
            tag_prompt = settings_service.get_tag_prompt()
        else:
            tag_prompt = compose_tag_prompt(tag_prompt)

        # Tag image
        tagger = get_tagger(db=db, user_id=user_id)
        result = run_async(tagger.tag_image(image_data, image.mime_type, tag_prompt))

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            tags=result.tags,
            tagging_model=result.model,
            tagging_prompt_version=result.prompt_version,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.TAGGED)
        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1, result={"tags": result.tags})

        # Auto-chain: re-embed if description exists (embedding depends on tags)
        image = image_service.get_image(image_id)
        if image and image.image_metadata and image.image_metadata.description_long:
            embed_image.delay(image_id, user_id)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task tag_image completed for image {image_id} in {elapsed:.0f}ms ({len(result.tags)} tags)",
                  task_name="tag_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "image_id": image_id, "tags": result.tags}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to tag image {image_id}: {err_msg}")
        write_log(category=LogCategory.TASK, message=f"Task tag_image failed for image {image_id}: {err_msg}",
                  level=LogLevel.ERROR, task_name="tag_image", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": err_msg}, user_id=user_id)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        image_service.update_status(image_id, ImageStatus.FAILED, err_msg)
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def describe_image(self, image_id: int, user_id: int, description_prompt: str | None = None, job_id: int | None = None) -> dict:
    """
    Generate a detailed description for an image.

    Pipeline stage: 4
    """
    write_log(category=LogCategory.TASK, message=f"Task describe_image started for image {image_id}",
              task_name="describe_image", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db, user_id)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        # Get image data
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get composed prompt: settings default or wrap user-provided guidance
        if description_prompt is None:
            settings_service = get_settings_service(db, user_id)
            description_prompt = settings_service.get_description_prompt()
        else:
            description_prompt = compose_description_prompt(description_prompt)

        # Generate description
        describer = get_describer(db=db, user_id=user_id)
        result = run_async(describer.describe_image(image_data, image.mime_type, description_prompt))

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            description_long=result.description,
            caption_model=result.model,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.DESCRIBED)
        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1)

        # Auto-chain: re-embed if tags exist (embedding depends on description)
        image = image_service.get_image(image_id)
        if image and image.image_metadata and image.image_metadata.tags:
            embed_image.delay(image_id, user_id)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task describe_image completed for image {image_id} in {elapsed:.0f}ms",
                  task_name="describe_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "image_id": image_id}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to describe image {image_id}: {err_msg}")
        write_log(category=LogCategory.TASK, message=f"Task describe_image failed for image {image_id}: {err_msg}",
                  level=LogLevel.ERROR, task_name="describe_image", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": err_msg}, user_id=user_id)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        image_service.update_status(image_id, ImageStatus.FAILED, err_msg)
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def embed_image(self, image_id: int, user_id: int, job_id: int | None = None) -> dict:
    """
    Generate embedding for an image based on its tags and description.

    Pipeline stage: 5
    """
    write_log(category=LogCategory.TASK, message=f"Task embed_image started for image {image_id}",
              task_name="embed_image", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db, user_id)
        image = image_service.get_image(image_id)

        if not image or not image.image_metadata:
            return {"status": "error", "message": "Image or metadata not found"}

        # Build text for embedding
        metadata = image.image_metadata
        text_parts = []

        # Add tags
        if metadata.tags:
            text_parts.append("Tags: " + ", ".join(metadata.tags))

        # Add description
        if metadata.description_long:
            text_parts.append(metadata.description_long)

        text = "\n".join(text_parts)

        # Generate embedding
        embedder = get_embedder(db=db, user_id=user_id)
        result = run_async(embedder.embed_text(text))

        # Save embedding
        image_service.save_metadata(
            image_id=image_id,
            embedding=result.embedding,
            embedding_model=result.model,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.EMBEDDED)
        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1, result={"dimensions": result.dimensions})

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task embed_image completed for image {image_id} in {elapsed:.0f}ms",
                  task_name="embed_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "image_id": image_id, "dimensions": result.dimensions}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Failed to embed image {image_id}: {e}")
        write_log(category=LogCategory.TASK, message=f"Task embed_image failed for image {image_id}: {e}",
                  level=LogLevel.ERROR, task_name="embed_image", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": _unwrap_error(e)}, user_id=user_id)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=_unwrap_error(e))
        image_service.update_status(image_id, ImageStatus.FAILED, _unwrap_error(e))
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def tag_and_describe_image(
    self, image_id: int, user_id: int, tag_prompt: str | None = None, description_prompt: str | None = None
) -> dict:
    """
    Combined task to tag and describe an image.

    This is more efficient as it only loads the image once.
    """
    db = get_db()
    try:
        image_service = get_image_service(db, user_id)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        # Get image data once
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get composed prompts: settings default or wrap user-provided guidance
        settings_service = get_settings_service(db, user_id)
        if tag_prompt is None:
            tag_prompt = settings_service.get_tag_prompt()
        else:
            tag_prompt = compose_tag_prompt(tag_prompt)
        if description_prompt is None:
            description_prompt = settings_service.get_description_prompt()
        else:
            description_prompt = compose_description_prompt(description_prompt)

        # Tag image
        tagger = get_tagger(db=db, user_id=user_id)
        tag_result = run_async(tagger.tag_image(image_data, image.mime_type, tag_prompt))

        # Describe image
        describer = get_describer(db=db, user_id=user_id)
        description_result = run_async(describer.describe_image(image_data, image.mime_type, description_prompt))

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            tags=tag_result.tags,
            description_long=description_result.description,
            tagging_model=tag_result.model,
            tagging_prompt_version=tag_result.prompt_version,
            caption_model=description_result.model,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.DESCRIBED)

        logger.info(f"Tagged and described image {image_id}")
        return {
            "status": "success",
            "image_id": image_id,
            "tags": tag_result.tags,
        }

    except Exception as e:
        logger.error(f"Failed to process image {image_id}: {e}")
        image_service.update_status(image_id, ImageStatus.FAILED, _unwrap_error(e))
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def cluster_all_images(self, user_id: int, job_id: int | None = None) -> dict:
    """
    Cluster all embedded images.

    Pipeline stage: 6
    """
    write_log(category=LogCategory.TASK, message="Task cluster_all_images started",
              task_name="cluster_all_images", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        # Update job status
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.utcnow()
                db.commit()

        image_service = get_image_service(db, user_id)
        cluster_service = get_cluster_service(db, user_id)
        clustering_service = get_clustering_service()

        # Get all embedded images
        images = image_service.get_images_for_clustering()

        if len(images) < 2:
            logger.warning("Not enough images for clustering")
            return {"status": "skipped", "message": "Not enough images for clustering"}

        # Build embeddings matrix
        embeddings = []
        image_ids = []

        for image in images:
            if image.image_metadata and image.image_metadata.embedding is not None:
                embeddings.append(image.image_metadata.embedding)
                image_ids.append(image.id)

        if len(embeddings) < 2:
            return {"status": "skipped", "message": "Not enough embeddings for clustering"}

        embeddings_array = np.array(embeddings)

        # Read clustering config from DB
        settings_service = get_settings_service(db, user_id)
        clustering_config = settings_service.get_clustering_config()

        # Run clustering
        result = clustering_service.cluster(embeddings_array, params=clustering_config)

        # Delete old clusters (keep only latest run)
        cluster_service.delete_old_clusters()

        # Create new clusters
        clusters = cluster_service.create_clusters_from_result(
            result, image_ids, embeddings_array
        )

        # Update image statuses
        for image_id in image_ids:
            image_service.update_status(image_id, ImageStatus.CLUSTERED)

        # Update job
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.utcnow()
                job.result = {
                    "n_clusters": result.n_clusters,
                    "n_images": len(image_ids),
                    "run_id": result.run_id,
                }
                db.commit()

        # Auto-chain: summarize all new clusters
        cluster_ids = [c.id for c in clusters]
        if cluster_ids:
            logger.info(f"Auto-dispatching summarization for {len(cluster_ids)} clusters")
            summarize_clusters.delay(cluster_ids, user_id)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task cluster_all_images completed in {elapsed:.0f}ms ({len(image_ids)} images, {result.n_clusters} clusters)",
                  task_name="cluster_all_images", job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {
            "status": "success",
            "n_clusters": result.n_clusters,
            "n_images": len(image_ids),
            "run_id": result.run_id,
            "cluster_ids": cluster_ids,
        }

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Clustering failed: {e}")
        write_log(category=LogCategory.TASK, message=f"Task cluster_all_images failed: {e}",
                  level=LogLevel.ERROR, task_name="cluster_all_images", job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": _unwrap_error(e)}, user_id=user_id)
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def summarize_cluster(self, cluster_id: int, user_id: int) -> dict:
    """
    Generate AI summary for a cluster.

    Pipeline stage: 7
    """
    write_log(category=LogCategory.TASK, message=f"Task summarize_cluster started for cluster {cluster_id}",
              task_name="summarize_cluster", user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        cluster_service = get_cluster_service(db, user_id)
        clustering_service = get_clustering_service()

        cluster = cluster_service.get_cluster(cluster_id)
        if not cluster:
            return {"status": "error", "message": "Cluster not found"}

        # Get cluster images
        images = cluster_service.get_cluster_images(cluster_id, include_outliers=False)

        if not images:
            return {"status": "skipped", "message": "No images in cluster"}

        # Collect tags and descriptions
        all_tags = []
        descriptions = []

        for image in images:
            if image.image_metadata:
                if image.image_metadata.tags:
                    all_tags.append(image.image_metadata.tags)
                if image.image_metadata.description_long:
                    descriptions.append(image.image_metadata.description_long)

        # Compute common tags
        common_tags = clustering_service.compute_common_tags(all_tags)

        # Generate summary
        summarizer = get_cluster_summarizer(db=db, user_id=user_id)
        result = run_async(
            summarizer.summarize_cluster(common_tags, descriptions, cluster.size)
        )

        # Update cluster
        cluster_service.update_cluster_summary(
            cluster_id=cluster_id,
            summary_title=result.summary_title,
            summary_description=result.summary_description,
            common_tags=common_tags,
            summarization_model=result.model,
        )

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task summarize_cluster completed for cluster {cluster_id} in {elapsed:.0f}ms: {result.summary_title}",
                  task_name="summarize_cluster", duration_ms=round(elapsed, 1), user_id=user_id)
        return {
            "status": "success",
            "cluster_id": cluster_id,
            "title": result.summary_title,
        }

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Failed to summarize cluster {cluster_id}: {e}")
        write_log(category=LogCategory.TASK, message=f"Task summarize_cluster failed for cluster {cluster_id}: {e}",
                  level=LogLevel.ERROR, task_name="summarize_cluster",
                  duration_ms=round(elapsed, 1), extra={"error": _unwrap_error(e)}, user_id=user_id)
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def summarize_clusters(self, cluster_ids: list[int], user_id: int, job_id: int | None = None) -> dict:
    """Summarize multiple clusters."""
    db = get_db()
    try:
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.utcnow()
                job.total_items = len(cluster_ids)
                db.commit()

        results = []
        for i, cluster_id in enumerate(cluster_ids):
            result = summarize_cluster(cluster_id, user_id)
            results.append(result)

            if job_id:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job:
                    job.progress = i + 1
                    db.commit()

        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.utcnow()
                db.commit()

        return {"status": "success", "results": results}

    except Exception as e:
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def process_image_pipeline(
    self, image_id: int, user_id: int, tag_prompt: str | None = None, description_prompt: str | None = None, job_id: int | None = None
) -> dict:
    """
    Run full pipeline for a single image: tag -> describe -> embed.

    Clusters are run separately after batch ingestion.
    """
    write_log(category=LogCategory.TASK, message=f"Task process_image_pipeline started for image {image_id}",
              task_name="process_image_pipeline", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db, user_id)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        # Get image data once
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get composed prompts: settings default or wrap user-provided guidance
        settings_service = get_settings_service(db, user_id)
        if tag_prompt is None:
            tag_prompt = settings_service.get_tag_prompt()
        else:
            tag_prompt = compose_tag_prompt(tag_prompt)
        if description_prompt is None:
            description_prompt = settings_service.get_description_prompt()
        else:
            description_prompt = compose_description_prompt(description_prompt)

        # Tag
        tagger = get_tagger(db=db, user_id=user_id)
        tag_result = run_async(tagger.tag_image(image_data, image.mime_type, tag_prompt))

        # Describe
        describer = get_describer(db=db, user_id=user_id)
        description_result = run_async(describer.describe_image(image_data, image.mime_type, description_prompt))

        # Build text for embedding
        text_parts = []
        if tag_result.tags:
            text_parts.append("Tags: " + ", ".join(tag_result.tags))
        text_parts.append(description_result.description)
        text = "\n".join(text_parts)

        # Embed
        embedder = get_embedder(db=db, user_id=user_id)
        embed_result = run_async(embedder.embed_text(text))

        # Save all metadata at once
        image_service.save_metadata(
            image_id=image_id,
            tags=tag_result.tags,
            description_long=description_result.description,
            embedding=embed_result.embedding,
            tagging_model=tag_result.model,
            tagging_prompt_version=tag_result.prompt_version,
            caption_model=description_result.model,
            embedding_model=embed_result.model,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.EMBEDDED)
        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1, result={"tags": tag_result.tags})

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task process_image_pipeline completed for image {image_id} in {elapsed:.0f}ms",
                  task_name="process_image_pipeline", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {
            "status": "success",
            "image_id": image_id,
            "tags": tag_result.tags,
        }

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Pipeline failed for image {image_id}: {err_msg}")
        write_log(category=LogCategory.TASK, message=f"Task process_image_pipeline failed for image {image_id}: {err_msg}",
                  level=LogLevel.ERROR, task_name="process_image_pipeline", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": err_msg}, user_id=user_id)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        image_service.update_status(image_id, ImageStatus.FAILED, _unwrap_error(e))
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def run_full_pipeline(self, job_id: int, user_id: int) -> dict:
    """
    Run full pipeline: process all pending images, then cluster and summarize.
    """
    write_log(category=LogCategory.TASK, message="Task run_full_pipeline started",
              task_name="run_full_pipeline", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            db.commit()

        image_service = get_image_service(db, user_id)

        # Get images that need processing
        pending_images = image_service.get_images(
            status=ImageStatus.INGESTED, limit=1000
        )

        if job:
            job.total_items = len(pending_images)
            db.commit()

        # Process each image
        processed = 0
        failed = 0

        for i, image in enumerate(pending_images):
            try:
                process_image_pipeline.delay(image.id, user_id)
                processed += 1
            except Exception as e:
                logger.error(f"Failed to queue image {image.id}: {e}")
                failed += 1

            if job:
                job.progress = i + 1
                db.commit()

        # Note: Clustering should be triggered separately after images are processed

        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.result = {
                "processed": processed,
                "failed": failed,
                "total": len(pending_images),
            }
            db.commit()

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task run_full_pipeline completed in {elapsed:.0f}ms ({processed} processed, {failed} failed)",
                  task_name="run_full_pipeline", job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {
            "status": "success",
            "processed": processed,
            "failed": failed,
        }

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Full pipeline failed: {e}")
        write_log(category=LogCategory.TASK, message=f"Task run_full_pipeline failed: {e}",
                  level=LogLevel.ERROR, task_name="run_full_pipeline", job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": _unwrap_error(e)}, user_id=user_id)
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, queue='clustering')
def run_batch_reprocess(self, job_id: int, user_id: int, image_ids: list[int]) -> dict:
    """
    Reprocess a batch of images: reset each to INGESTED, dispatch process_image_pipeline,
    then poll until all images have finished processing.

    Idempotent: if tasks were already dispatched (e.g. after worker restart / re-delivery),
    Phase 1 is skipped and we go straight to polling.
    """
    write_log(category=LogCategory.TASK, message=f"Task run_batch_reprocess started ({len(image_ids)} images)",
              task_name="run_batch_reprocess", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        # Check if this job was already cancelled (e.g. user cancelled while we were re-delivered)
        if job and job.status == JobStatus.CANCELLED:
            logger.info(f"Batch reprocess job {job_id} already cancelled, skipping")
            return {"status": "cancelled", "total": len(image_ids)}

        # Check idempotency: if tasks were already dispatched, skip Phase 1
        already_dispatched = False
        if job and isinstance(job.result, dict) and job.result.get("dispatched"):
            already_dispatched = True
            logger.info(f"Batch reprocess job {job_id} already dispatched, skipping to Phase 2")
            write_log(category=LogCategory.TASK,
                      message=f"Re-delivery detected for job {job_id}, skipping dispatch (already sent)",
                      task_name="run_batch_reprocess", job_id=job_id, user_id=user_id)

        if job and not already_dispatched:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            job.total_items = len(image_ids)
            job.result = {"image_ids": image_ids}
            db.commit()

        image_service = get_image_service(db, user_id)
        queued = 0

        # Phase 1: Reset images and dispatch pipeline tasks (skipped on re-delivery)
        if not already_dispatched:
            for image_id in image_ids:
                try:
                    image_service.update_status(image_id, ImageStatus.INGESTED)
                    process_image_pipeline.delay(image_id, user_id)
                    queued += 1
                except Exception as e:
                    logger.error(f"Failed to queue reprocess for image {image_id}: {e}")

            # Mark dispatched BEFORE polling so re-delivery skips Phase 1
            if job:
                job.result = {"image_ids": image_ids, "dispatched": True, "queued": queued}
                db.commit()

        # Phase 2: Poll until all images have finished (no longer INGESTED)
        image_id_set = set(image_ids)
        poll_interval = 5  # seconds
        while True:
            # Re-check if job was cancelled during polling
            db.expire_all()
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.status == JobStatus.CANCELLED:
                logger.info(f"Batch reprocess job {job_id} cancelled during polling")
                return {"status": "cancelled", "total": len(image_ids)}

            done_count = (
                db.query(Image)
                .filter(
                    Image.id.in_(image_id_set),
                    Image.status != ImageStatus.INGESTED,
                )
                .count()
            )

            if job:
                job.progress = done_count
                db.commit()

            if done_count >= len(image_ids):
                break

            time.sleep(poll_interval)

        # Count outcomes
        failed_count = (
            db.query(Image)
            .filter(Image.id.in_(image_id_set), Image.status == ImageStatus.FAILED)
            .count()
        )
        succeeded = len(image_ids) - failed_count

        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.result = {
                "total": len(image_ids),
                "queued": queued,
                "succeeded": succeeded,
                "failed": failed_count,
                "image_ids": image_ids,
                "dispatched": True,
            }
            db.commit()

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task run_batch_reprocess completed in {elapsed:.0f}ms ({succeeded} succeeded, {failed_count} failed)",
                  task_name="run_batch_reprocess", job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "total": len(image_ids), "succeeded": succeeded, "failed": failed_count}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Batch reprocess failed: {e}")
        write_log(category=LogCategory.TASK, message=f"Task run_batch_reprocess failed: {e}",
                  level=LogLevel.ERROR, task_name="run_batch_reprocess", job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": _unwrap_error(e)}, user_id=user_id)
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def delete_folder_with_images(self, folder_id: int, user_id: int, job_id: int) -> dict:
    """
    Delete a folder and all its images in the background.

    Creates a DB session, calls folder_service.delete_folder_with_images(),
    dispatches storage cleanup, and updates the Job record.
    """
    write_log(category=LogCategory.TASK,
              message=f"Task delete_folder_with_images started for folder {folder_id}",
              task_name="delete_folder_with_images", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        from app.services.folder_service import get_folder_service
        folder_service = get_folder_service(db, user_id)

        # Delete cover composite file before deleting the folder
        from app.services.storage import get_storage_service
        storage = get_storage_service()
        storage.delete_folder_cover_sync(folder_id)

        result = folder_service.delete_folder_with_images(folder_id)
        if result is None:
            _update_job_status(db, job_id, JobStatus.FAILED, error_message="Folder not found")
            return {"status": "error", "message": "Folder not found"}

        # Fire-and-forget storage cleanup
        if result["image_files"]:
            cleanup_storage_files.delay(result["image_files"])

        _update_job_status(
            db, job_id, JobStatus.COMPLETED,
            progress=result["images_deleted"],
            result={"images_deleted": result["images_deleted"], "folder_id": folder_id},
        )

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task delete_folder_with_images completed for folder {folder_id} in {elapsed:.0f}ms ({result['images_deleted']} images deleted)",
                  task_name="delete_folder_with_images", job_id=job_id,
                  duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "images_deleted": result["images_deleted"]}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to delete folder {folder_id}: {err_msg}")
        write_log(category=LogCategory.TASK,
                  message=f"Task delete_folder_with_images failed for folder {folder_id}: {err_msg}",
                  level=LogLevel.ERROR, task_name="delete_folder_with_images",
                  job_id=job_id, duration_ms=round(elapsed, 1),
                  extra={"error": err_msg}, user_id=user_id)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        raise
    finally:
        db.close()


@celery_app.task
def cleanup_storage_files(image_files: list[dict]) -> dict:
    """
    Fire-and-forget task to delete image files from storage.

    Args:
        image_files: List of {"object_key": str, "thumbnail_uris": [str, ...]}
    """
    from app.services.storage import get_storage_service

    storage = get_storage_service()
    total_deleted = 0
    total_failed = 0

    for entry in image_files:
        result = run_async(
            storage.delete_image_files(entry["object_key"], entry.get("thumbnail_uris", []))
        )
        total_deleted += result["deleted"]
        total_failed += result["failed"]

    logger.info(f"Storage cleanup: {total_deleted} files deleted, {total_failed} failed")
    return {"deleted": total_deleted, "failed": total_failed}


@celery_app.task
def cleanup_old_pipeline_logs():
    """Periodic cleanup of old pipeline log entries."""
    from app.services.log_service import cleanup_old_logs as _cleanup
    count = _cleanup(days=7)
    if count:
        logger.info(f"Cleaned up {count} old pipeline log entries")
