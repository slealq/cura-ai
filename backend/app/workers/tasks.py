"""Celery tasks for the image processing pipeline."""
import asyncio
import logging
import time
from datetime import datetime

import numpy as np
from celery import chain, chord, group
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import Image, ImageMetadata, ImageStatus, Job, JobStatus, JobType
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers import get_cluster_summarizer, get_describer, get_embedder, get_tagger
from app.services.cluster_service import get_cluster_service
from app.services.clustering import get_clustering_service
from app.services.image_service import get_image_service
from app.services.log_service import write_log
from app.services.settings_service import get_settings_service
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def get_db() -> Session:
    """Get database session for worker."""
    return SessionLocal()


def run_async(coro):
    """Run async function in sync context."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
        # Create new loop for nested async
        new_loop = asyncio.new_event_loop()
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    return loop.run_until_complete(coro)


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


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def tag_image(self, image_id: int, tag_guidance: str | None = None, job_id: int | None = None) -> dict:
    """
    Tag an image with categorization tags.

    Pipeline stage: 3
    """
    write_log(category=LogCategory.TASK, message=f"Task tag_image started for image {image_id}",
              task_name="tag_image", image_id=image_id, job_id=job_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db)
        image = image_service.get_image(image_id)

        if not image:
            logger.error(f"Image {image_id} not found")
            return {"status": "error", "message": "Image not found"}

        # Get image data
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get default guidance if not provided
        if tag_guidance is None:
            settings_service = get_settings_service(db)
            tag_guidance = settings_service.get_default_tag_guidance()

        # Tag image
        tagger = get_tagger()
        result = run_async(tagger.tag_image(image_data, image.mime_type, tag_guidance))

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
            embed_image.delay(image_id)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task tag_image completed for image {image_id} in {elapsed:.0f}ms ({len(result.tags)} tags)",
                  task_name="tag_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1))
        return {"status": "success", "image_id": image_id, "tags": result.tags}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Failed to tag image {image_id}: {e}")
        write_log(category=LogCategory.TASK, message=f"Task tag_image failed for image {image_id}: {e}",
                  level=LogLevel.ERROR, task_name="tag_image", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": str(e)})
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=str(e))
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def describe_image(self, image_id: int, description_guidance: str | None = None, job_id: int | None = None) -> dict:
    """
    Generate a detailed description for an image.

    Pipeline stage: 4
    """
    write_log(category=LogCategory.TASK, message=f"Task describe_image started for image {image_id}",
              task_name="describe_image", image_id=image_id, job_id=job_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        # Get image data
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get default guidance if not provided
        if description_guidance is None:
            settings_service = get_settings_service(db)
            description_guidance = settings_service.get_default_description_guidance()

        # Generate description
        describer = get_describer()
        result = run_async(describer.describe_image(image_data, image.mime_type, description_guidance))

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
            embed_image.delay(image_id)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task describe_image completed for image {image_id} in {elapsed:.0f}ms",
                  task_name="describe_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1))
        return {"status": "success", "image_id": image_id}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Failed to describe image {image_id}: {e}")
        write_log(category=LogCategory.TASK, message=f"Task describe_image failed for image {image_id}: {e}",
                  level=LogLevel.ERROR, task_name="describe_image", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": str(e)})
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=str(e))
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def embed_image(self, image_id: int, job_id: int | None = None) -> dict:
    """
    Generate embedding for an image based on its tags and description.

    Pipeline stage: 5
    """
    write_log(category=LogCategory.TASK, message=f"Task embed_image started for image {image_id}",
              task_name="embed_image", image_id=image_id, job_id=job_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db)
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
        embedder = get_embedder()
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
                  task_name="embed_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1))
        return {"status": "success", "image_id": image_id, "dimensions": result.dimensions}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Failed to embed image {image_id}: {e}")
        write_log(category=LogCategory.TASK, message=f"Task embed_image failed for image {image_id}: {e}",
                  level=LogLevel.ERROR, task_name="embed_image", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": str(e)})
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=str(e))
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True)
def tag_and_describe_image(
    self, image_id: int, tag_guidance: str | None = None, description_guidance: str | None = None
) -> dict:
    """
    Combined task to tag and describe an image.

    This is more efficient as it only loads the image once.
    """
    db = get_db()
    try:
        image_service = get_image_service(db)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        # Get image data once
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get default guidance if not provided
        settings_service = get_settings_service(db)
        if tag_guidance is None:
            tag_guidance = settings_service.get_default_tag_guidance()
        if description_guidance is None:
            description_guidance = settings_service.get_default_description_guidance()

        # Tag image
        tagger = get_tagger()
        tag_result = run_async(tagger.tag_image(image_data, image.mime_type, tag_guidance))

        # Describe image
        describer = get_describer()
        description_result = run_async(describer.describe_image(image_data, image.mime_type, description_guidance))

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
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def cluster_all_images(self, job_id: int | None = None) -> dict:
    """
    Cluster all embedded images.

    Pipeline stage: 6
    """
    write_log(category=LogCategory.TASK, message="Task cluster_all_images started",
              task_name="cluster_all_images", job_id=job_id)
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

        image_service = get_image_service(db)
        cluster_service = get_cluster_service(db)
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
            if image.image_metadata and image.image_metadata.embedding:
                embeddings.append(image.image_metadata.embedding)
                image_ids.append(image.id)

        if len(embeddings) < 2:
            return {"status": "skipped", "message": "Not enough embeddings for clustering"}

        embeddings_array = np.array(embeddings)

        # Run clustering
        result = clustering_service.cluster(embeddings_array)

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

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task cluster_all_images completed in {elapsed:.0f}ms ({len(image_ids)} images, {result.n_clusters} clusters)",
                  task_name="cluster_all_images", job_id=job_id, duration_ms=round(elapsed, 1))
        return {
            "status": "success",
            "n_clusters": result.n_clusters,
            "n_images": len(image_ids),
            "run_id": result.run_id,
            "cluster_ids": [c.id for c in clusters],
        }

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Clustering failed: {e}")
        write_log(category=LogCategory.TASK, message=f"Task cluster_all_images failed: {e}",
                  level=LogLevel.ERROR, task_name="cluster_all_images", job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": str(e)})
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
def summarize_cluster(self, cluster_id: int) -> dict:
    """
    Generate AI summary for a cluster.

    Pipeline stage: 7
    """
    write_log(category=LogCategory.TASK, message=f"Task summarize_cluster started for cluster {cluster_id}",
              task_name="summarize_cluster")
    task_start = time.monotonic()
    db = get_db()
    try:
        cluster_service = get_cluster_service(db)
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
        summarizer = get_cluster_summarizer()
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
                  task_name="summarize_cluster", duration_ms=round(elapsed, 1))
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
                  duration_ms=round(elapsed, 1), extra={"error": str(e)})
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def summarize_clusters(self, cluster_ids: list[int], job_id: int | None = None) -> dict:
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
            result = summarize_cluster(cluster_id)
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
    self, image_id: int, tag_guidance: str | None = None, description_guidance: str | None = None, job_id: int | None = None
) -> dict:
    """
    Run full pipeline for a single image: tag -> describe -> embed.

    Clusters are run separately after batch ingestion.
    """
    write_log(category=LogCategory.TASK, message=f"Task process_image_pipeline started for image {image_id}",
              task_name="process_image_pipeline", image_id=image_id, job_id=job_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        # Get image data once
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Get default guidance if not provided
        settings_service = get_settings_service(db)
        if tag_guidance is None:
            tag_guidance = settings_service.get_default_tag_guidance()
        if description_guidance is None:
            description_guidance = settings_service.get_default_description_guidance()

        # Tag
        tagger = get_tagger()
        tag_result = run_async(tagger.tag_image(image_data, image.mime_type, tag_guidance))

        # Describe
        describer = get_describer()
        description_result = run_async(describer.describe_image(image_data, image.mime_type, description_guidance))

        # Build text for embedding
        text_parts = []
        if tag_result.tags:
            text_parts.append("Tags: " + ", ".join(tag_result.tags))
        text_parts.append(description_result.description)
        text = "\n".join(text_parts)

        # Embed
        embedder = get_embedder()
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
                  task_name="process_image_pipeline", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1))
        return {
            "status": "success",
            "image_id": image_id,
            "tags": tag_result.tags,
        }

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Pipeline failed for image {image_id}: {e}")
        write_log(category=LogCategory.TASK, message=f"Task process_image_pipeline failed for image {image_id}: {e}",
                  level=LogLevel.ERROR, task_name="process_image_pipeline", image_id=image_id, job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": str(e)})
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=str(e))
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def run_full_pipeline(self, job_id: int) -> dict:
    """
    Run full pipeline: process all pending images, then cluster and summarize.
    """
    write_log(category=LogCategory.TASK, message="Task run_full_pipeline started",
              task_name="run_full_pipeline", job_id=job_id)
    task_start = time.monotonic()
    db = get_db()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            db.commit()

        image_service = get_image_service(db)

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
                process_image_pipeline.delay(image.id)
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
                  task_name="run_full_pipeline", job_id=job_id, duration_ms=round(elapsed, 1))
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
                  duration_ms=round(elapsed, 1), extra={"error": str(e)})
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                db.commit()
        raise
    finally:
        db.close()


@celery_app.task
def cleanup_old_pipeline_logs():
    """Periodic cleanup of old pipeline log entries."""
    from app.services.log_service import cleanup_old_logs as _cleanup
    count = _cleanup(days=7)
    if count:
        logger.info(f"Cleaned up {count} old pipeline log entries")
