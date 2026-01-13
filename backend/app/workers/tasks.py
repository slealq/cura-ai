"""Celery tasks for the image processing pipeline."""
import asyncio
import logging
from datetime import datetime

import numpy as np
from celery import chain, chord, group
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import Image, ImageMetadata, ImageStatus, Job, JobStatus, JobType
from app.providers import get_captioner, get_cluster_summarizer, get_embedder, get_tagger
from app.services.cluster_service import get_cluster_service
from app.services.clustering import get_clustering_service
from app.services.image_service import get_image_service
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


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def tag_image(self, image_id: int) -> dict:
    """
    Tag an image with structured metadata.

    Pipeline stage: 3
    """
    db = get_db()
    try:
        image_service = get_image_service(db)
        image = image_service.get_image(image_id)

        if not image:
            logger.error(f"Image {image_id} not found")
            return {"status": "error", "message": "Image not found"}

        # Get image data
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Tag image
        tagger = get_tagger()
        result = run_async(tagger.tag_image(image_data, image.mime_type))

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            tags=result.tags,
            tagging_model=result.model,
            tagging_prompt_version=result.prompt_version,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.TAGGED)

        logger.info(f"Tagged image {image_id}")
        return {"status": "success", "image_id": image_id, "tags": result.tags}

    except Exception as e:
        logger.error(f"Failed to tag image {image_id}: {e}")
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def describe_image(self, image_id: int) -> dict:
    """
    Generate caption and description for an image.

    Pipeline stage: 4
    """
    db = get_db()
    try:
        image_service = get_image_service(db)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        # Get image data
        image_data = run_async(image_service.get_image_data(image_id))
        if not image_data:
            raise Exception("Failed to load image data")

        # Generate captions
        captioner = get_captioner()
        result = run_async(captioner.caption_image(image_data, image.mime_type))

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            caption_short=result.caption_short,
            description_long=result.description_long,
            caption_model=result.model,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.DESCRIBED)

        logger.info(f"Described image {image_id}")
        return {
            "status": "success",
            "image_id": image_id,
            "caption": result.caption_short,
        }

    except Exception as e:
        logger.error(f"Failed to describe image {image_id}: {e}")
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def embed_image(self, image_id: int) -> dict:
    """
    Generate embedding for an image based on its tags and description.

    Pipeline stage: 5
    """
    db = get_db()
    try:
        image_service = get_image_service(db)
        image = image_service.get_image(image_id)

        if not image or not image.image_metadata:
            return {"status": "error", "message": "Image or metadata not found"}

        # Build text for embedding
        metadata = image.image_metadata
        text_parts = []

        # Add tags
        if metadata.tags:
            for category, values in metadata.tags.items():
                if values:
                    text_parts.append(f"{category}: {', '.join(values)}")

        # Add caption and description
        if metadata.caption_short:
            text_parts.append(metadata.caption_short)
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

        logger.info(f"Embedded image {image_id}")
        return {"status": "success", "image_id": image_id, "dimensions": result.dimensions}

    except Exception as e:
        logger.error(f"Failed to embed image {image_id}: {e}")
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True)
def tag_and_describe_image(self, image_id: int) -> dict:
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

        # Tag image
        tagger = get_tagger()
        tag_result = run_async(tagger.tag_image(image_data, image.mime_type))

        # Describe image
        captioner = get_captioner()
        caption_result = run_async(captioner.caption_image(image_data, image.mime_type))

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            tags=tag_result.tags,
            caption_short=caption_result.caption_short,
            description_long=caption_result.description_long,
            tagging_model=tag_result.model,
            tagging_prompt_version=tag_result.prompt_version,
            caption_model=caption_result.model,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.DESCRIBED)

        logger.info(f"Tagged and described image {image_id}")
        return {
            "status": "success",
            "image_id": image_id,
            "tags": tag_result.tags,
            "caption": caption_result.caption_short,
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

        logger.info(f"Clustered {len(image_ids)} images into {result.n_clusters} clusters")
        return {
            "status": "success",
            "n_clusters": result.n_clusters,
            "n_images": len(image_ids),
            "run_id": result.run_id,
            "cluster_ids": [c.id for c in clusters],
        }

    except Exception as e:
        logger.error(f"Clustering failed: {e}")
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

        logger.info(f"Summarized cluster {cluster_id}: {result.summary_title}")
        return {
            "status": "success",
            "cluster_id": cluster_id,
            "title": result.summary_title,
        }

    except Exception as e:
        logger.error(f"Failed to summarize cluster {cluster_id}: {e}")
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
def process_image_pipeline(self, image_id: int) -> dict:
    """
    Run full pipeline for a single image: tag -> describe -> embed.

    Clusters are run separately after batch ingestion.
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

        # Tag
        tagger = get_tagger()
        tag_result = run_async(tagger.tag_image(image_data, image.mime_type))

        # Describe
        captioner = get_captioner()
        caption_result = run_async(captioner.caption_image(image_data, image.mime_type))

        # Build text for embedding
        text_parts = []
        for category, values in tag_result.tags.items():
            if values:
                text_parts.append(f"{category}: {', '.join(values)}")
        text_parts.append(caption_result.caption_short)
        text_parts.append(caption_result.description_long)
        text = "\n".join(text_parts)

        # Embed
        embedder = get_embedder()
        embed_result = run_async(embedder.embed_text(text))

        # Save all metadata at once
        image_service.save_metadata(
            image_id=image_id,
            tags=tag_result.tags,
            caption_short=caption_result.caption_short,
            description_long=caption_result.description_long,
            embedding=embed_result.embedding,
            tagging_model=tag_result.model,
            tagging_prompt_version=tag_result.prompt_version,
            caption_model=caption_result.model,
            embedding_model=embed_result.model,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.EMBEDDED)

        logger.info(f"Completed pipeline for image {image_id}")
        return {
            "status": "success",
            "image_id": image_id,
            "tags": tag_result.tags,
            "caption": caption_result.caption_short,
        }

    except Exception as e:
        logger.error(f"Pipeline failed for image {image_id}: {e}")
        image_service.update_status(image_id, ImageStatus.FAILED, str(e))
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def run_full_pipeline(self, job_id: int) -> dict:
    """
    Run full pipeline: process all pending images, then cluster and summarize.
    """
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

        return {
            "status": "success",
            "processed": processed,
            "failed": failed,
        }

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
