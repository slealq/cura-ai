"""Celery tasks for LoRA training and image generation."""
import asyncio
import base64
import io
import logging
import time
import zipfile
from datetime import datetime

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import Job, JobStatus, JobType
from app.models.generated_image import GeneratedImage, GenerationStatus
from app.models.lora_model import LoraModel, LoraModelStatus
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers import get_generator, get_trainer
from app.services.generation_service import get_generation_service
from app.services.image_service import get_image_service
from app.services.log_service import write_log
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_db() -> Session:
    """Get database session for worker."""
    return SessionLocal()


def _run_async(coro):
    """Run async function in sync context."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
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


def _unwrap_error(e: Exception) -> str:
    """Extract a readable error message."""
    if hasattr(e, 'last_attempt'):
        try:
            real = e.last_attempt.result()
        except Exception as inner:
            return str(inner)
    return str(e)


@celery_app.task(bind=True)
def train_lora(self, lora_model_id: int, job_id: int | None = None) -> dict:
    """
    Train a LoRA model from folder images via fal.ai.

    1. Load folder images, encode as base64 data URLs
    2. Submit to fal.ai via get_trainer()
    3. Poll until complete (check for job cancellation)
    4. Save result URL to LoraModel record
    """
    write_log(
        category=LogCategory.TASK,
        message=f"Task train_lora started for lora_model {lora_model_id}",
        task_name="train_lora",
        job_id=job_id,
    )
    task_start = time.monotonic()
    db = _get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        gen_service = get_generation_service(db)
        lora = gen_service.get_lora_model(lora_model_id)
        if not lora:
            return {"status": "error", "message": "LoRA model not found"}

        # Update status to training
        gen_service.update_lora_status(lora_model_id, LoraModelStatus.TRAINING)

        # Load source images (folder or cluster)
        image_service = get_image_service(db)

        if lora.folder_id:
            from app.models.folder import FolderImage
            folder_image_ids = [
                fi.image_id
                for fi in db.query(FolderImage).filter(FolderImage.folder_id == lora.folder_id).all()
            ]
        elif lora.cluster_id:
            from app.models.cluster import ClusterMembership
            folder_image_ids = [
                cm.image_id
                for cm in db.query(ClusterMembership).filter(
                    ClusterMembership.cluster_id == lora.cluster_id,
                    ClusterMembership.is_excluded == False,
                ).all()
            ]
        else:
            raise Exception("LoRA model has no associated folder or cluster")

        if len(folder_image_ids) < 5:
            raise Exception(f"Source has only {len(folder_image_ids)} images, minimum 5 required")

        # Get training config
        training_config = lora.training_config or {}
        steps = training_config.get("steps", 1000)
        is_style = training_config.get("is_style", False)
        use_captions = training_config.get("use_captions", False)
        caption_include_tags = training_config.get("caption_include_tags", True)
        caption_include_description = training_config.get("caption_include_description", True)

        # Instantiate trainer early so _ensure_fal_key() sets FAL_KEY
        # before any fal_client calls (e.g. upload)
        trainer = get_trainer(lora.training_provider, db=db)

        trainer_kwargs = {}

        if use_captions:
            # Build ZIP with images + per-image caption .txt files
            zip_buffer = io.BytesIO()
            image_count = 0
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for idx, img_id in enumerate(folder_image_ids):
                    image_data = _run_async(image_service.get_image_data(img_id))
                    if not image_data:
                        continue

                    image = image_service.get_image(img_id)
                    ext = "jpg"
                    if image.mime_type:
                        ext_map = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}
                        ext = ext_map.get(image.mime_type, "jpg")

                    prefix = f"{idx:04d}"
                    zf.writestr(f"{prefix}.{ext}", image_data)

                    # Build caption
                    caption_parts = []
                    caption_parts.append(lora.trigger_word)

                    metadata = image.image_metadata
                    if metadata:
                        tags_str = ""
                        if caption_include_tags and metadata.tags:
                            tags_str = ", ".join(metadata.tags)

                        desc_str = ""
                        if caption_include_description and metadata.description_long:
                            desc_str = metadata.description_long

                        if tags_str and desc_str:
                            caption_parts.append(f"{tags_str}. {desc_str}")
                        elif tags_str:
                            caption_parts.append(tags_str)
                        elif desc_str:
                            caption_parts.append(desc_str)

                    caption = ", ".join(caption_parts)
                    zf.writestr(f"{prefix}.txt", caption)
                    image_count += 1

            if image_count == 0:
                raise Exception("No image data could be loaded from source")

            logger.info(f"Created ZIP with {image_count} captioned images for LoRA training")

            # Upload ZIP to fal CDN
            import fal_client
            zip_bytes = zip_buffer.getvalue()
            zip_url = fal_client.upload(zip_bytes, "application/zip")
            logger.info(f"Uploaded training ZIP ({len(zip_bytes)} bytes) to fal CDN")

            # Override images_data_url with the ZIP URL
            trainer_kwargs["images_data_url"] = zip_url
            image_urls: list[str] = []
        else:
            # Default: encode images as base64 data URLs
            image_urls = []
            for img_id in folder_image_ids:
                image_data = _run_async(image_service.get_image_data(img_id))
                if image_data:
                    image = image_service.get_image(img_id)
                    mime = image.mime_type or "image/jpeg"
                    b64 = base64.b64encode(image_data).decode("utf-8")
                    image_urls.append(f"data:{mime};base64,{b64}")

            if not image_urls:
                raise Exception("No image data could be loaded from source")

            logger.info(f"Prepared {len(image_urls)} images for LoRA training")

        # Submit training
        request_id = _run_async(
            trainer.start_training(
                image_urls=image_urls,
                trigger_word=lora.trigger_word,
                steps=steps,
                is_style=is_style,
                **trainer_kwargs,
            )
        )

        logger.info(f"LoRA training submitted: request_id={request_id}")

        # Poll for completion
        poll_interval = 15  # seconds
        while True:
            # Check for cancellation
            db.expire_all()
            if job_id:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job and job.status == JobStatus.CANCELLED:
                    logger.info(f"LoRA training job {job_id} cancelled")
                    gen_service.update_lora_status(lora_model_id, LoraModelStatus.FAILED, "Cancelled by user")
                    return {"status": "cancelled"}

            status_info = _run_async(trainer.check_training_status(request_id))
            status_type = status_info.get("status", "")

            if status_type == "Completed":
                break
            elif "error" in status_type.lower() or status_info.get("error"):
                error_msg = status_info.get("error", "Training failed")
                raise Exception(error_msg)

            time.sleep(poll_interval)

        # Get result
        result = _run_async(trainer.get_training_result(request_id))

        # Update LoRA model
        gen_service.update_lora_status(
            lora_model_id,
            LoraModelStatus.COMPLETED,
            lora_url=result.lora_url,
            provider_metadata={"request_id": request_id, **(result.metadata or {})},
        )

        _update_job_status(
            db, job_id, JobStatus.COMPLETED,
            progress=1,
            result={"lora_url": result.lora_url, "request_id": request_id},
        )

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(
            category=LogCategory.TASK,
            message=f"Task train_lora completed for lora_model {lora_model_id} in {elapsed:.0f}ms",
            task_name="train_lora",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
        )
        return {"status": "success", "lora_model_id": lora_model_id, "lora_url": result.lora_url}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to train LoRA {lora_model_id}: {err_msg}")
        write_log(
            category=LogCategory.TASK,
            message=f"Task train_lora failed for lora_model {lora_model_id}: {err_msg}",
            level=LogLevel.ERROR,
            task_name="train_lora",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
            extra={"error": err_msg},
        )
        gen_service = get_generation_service(db)
        gen_service.update_lora_status(lora_model_id, LoraModelStatus.FAILED, err_msg)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        raise
    finally:
        db.close()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def generate_image(self, generated_image_id: int, job_id: int | None = None) -> dict:
    """
    Generate a single image via fal.ai.
    """
    write_log(
        category=LogCategory.TASK,
        message=f"Task generate_image started for generated_image {generated_image_id}",
        task_name="generate_image",
        job_id=job_id,
    )
    task_start = time.monotonic()
    db = _get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        gen_service = get_generation_service(db)
        gen = gen_service.get_generated_image(generated_image_id)
        if not gen:
            return {"status": "error", "message": "Generated image record not found"}

        # Mark as generating
        gen.status = GenerationStatus.GENERATING
        db.commit()

        # Get LoRA URL if applicable
        lora_url = None
        lora_scale = gen.lora_scale or 1.0
        if gen.lora_model_id:
            lora = gen_service.get_lora_model(gen.lora_model_id)
            if lora and lora.lora_url:
                lora_url = lora.lora_url

        # Get generation params
        params = gen.generation_params or {}

        # Generate
        generator = get_generator(gen.generation_provider, db=db)
        result = _run_async(
            generator.generate(
                prompt=gen.prompt,
                negative_prompt=gen.negative_prompt,
                width=params.get("width", 1024),
                height=params.get("height", 1024),
                num_inference_steps=params.get("num_inference_steps", 28),
                guidance_scale=params.get("guidance_scale", 3.5),
                seed=params.get("seed"),
                lora_url=lora_url,
                lora_scale=lora_scale,
            )
        )

        # Save result
        _run_async(
            gen_service.save_generated_result(
                generated_image_id=generated_image_id,
                image_data=result.image_data,
                width=result.width,
                height=result.height,
                seed=result.seed,
                provider_metadata=result.metadata,
            )
        )

        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(
            category=LogCategory.TASK,
            message=f"Task generate_image completed for generated_image {generated_image_id} in {elapsed:.0f}ms",
            task_name="generate_image",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
        )
        return {"status": "success", "generated_image_id": generated_image_id}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to generate image {generated_image_id}: {err_msg}")
        write_log(
            category=LogCategory.TASK,
            message=f"Task generate_image failed for generated_image {generated_image_id}: {err_msg}",
            level=LogLevel.ERROR,
            task_name="generate_image",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
            extra={"error": err_msg},
        )
        # Mark as failed
        gen = db.query(GeneratedImage).filter(GeneratedImage.id == generated_image_id).first()
        if gen:
            gen.status = GenerationStatus.FAILED
            gen.error_message = err_msg
            db.commit()
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        raise self.retry(exc=e)
    finally:
        db.close()


@celery_app.task(bind=True)
def batch_generate(self, generated_image_ids: list[int], job_id: int | None = None) -> dict:
    """
    Generate multiple images. Dispatches individual generate_image tasks and polls for completion.
    """
    write_log(
        category=LogCategory.TASK,
        message=f"Task batch_generate started ({len(generated_image_ids)} images)",
        task_name="batch_generate",
        job_id=job_id,
    )
    task_start = time.monotonic()
    db = _get_db()
    try:
        job = db.query(Job).filter(Job.id == job_id).first() if job_id else None

        if job and job.status == JobStatus.CANCELLED:
            return {"status": "cancelled", "total": len(generated_image_ids)}

        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            job.total_items = len(generated_image_ids)
            db.commit()

        # Dispatch individual tasks
        for gen_id in generated_image_ids:
            generate_image.delay(gen_id)

        # Poll for completion
        poll_interval = 5
        while True:
            db.expire_all()
            if job_id:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job and job.status == JobStatus.CANCELLED:
                    return {"status": "cancelled", "total": len(generated_image_ids)}

            done_count = (
                db.query(GeneratedImage)
                .filter(
                    GeneratedImage.id.in_(generated_image_ids),
                    GeneratedImage.status.in_([GenerationStatus.COMPLETED, GenerationStatus.FAILED]),
                )
                .count()
            )

            if job:
                job.progress = done_count
                db.commit()

            if done_count >= len(generated_image_ids):
                break

            time.sleep(poll_interval)

        # Count outcomes
        failed_count = (
            db.query(GeneratedImage)
            .filter(
                GeneratedImage.id.in_(generated_image_ids),
                GeneratedImage.status == GenerationStatus.FAILED,
            )
            .count()
        )
        succeeded = len(generated_image_ids) - failed_count

        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.result = {
                "total": len(generated_image_ids),
                "succeeded": succeeded,
                "failed": failed_count,
            }
            db.commit()

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(
            category=LogCategory.TASK,
            message=f"Task batch_generate completed in {elapsed:.0f}ms ({succeeded} succeeded, {failed_count} failed)",
            task_name="batch_generate",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
        )
        return {"status": "success", "total": len(generated_image_ids), "succeeded": succeeded, "failed": failed_count}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Batch generate failed: {err_msg}")
        write_log(
            category=LogCategory.TASK,
            message=f"Task batch_generate failed: {err_msg}",
            level=LogLevel.ERROR,
            task_name="batch_generate",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
            extra={"error": err_msg},
        )
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.FAILED
                job.error_message = err_msg
                db.commit()
        raise
    finally:
        db.close()
