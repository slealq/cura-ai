"""Celery tasks for LoRA training, image generation, and evaluation."""
import asyncio
import base64
import io
import logging
import random
import time
import uuid
import zipfile
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import Job, JobStatus
from app.models.generated_image import GeneratedImage, GenerationStatus
from app.models.lora_evaluation import EvaluationStatus
from app.models.lora_model import LoraModelStatus
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers import get_describer, get_embedder, get_evaluator, get_generator, get_trainer
from app.services.evaluation_service import get_evaluation_service
from app.services.generation_service import get_generation_service
from app.services.image_service import get_image_service
from app.services.log_service import write_log
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_db() -> Session:
    """Get database session for worker."""
    return SessionLocal()


def _run_async(coro):
    """Run async function in sync context (works in thread-pool workers)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
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


def _unwrap_error(e: Exception) -> str:
    """Extract a readable error message."""
    if hasattr(e, 'last_attempt'):
        try:
            e.last_attempt.result()
        except Exception as inner:
            return str(inner)
    return str(e)


def _download_lora_weights(db: Session, lora_model_id: int, lora_url: str, user_id: int) -> None:
    """Download LoRA safetensors file from provider CDN and store locally."""
    import hashlib

    import httpx

    from app.services.storage import get_storage_service

    logger.info(f"Downloading LoRA weights for model {lora_model_id} from {lora_url[:80]}...")

    response = httpx.get(lora_url, timeout=300, follow_redirects=True)
    response.raise_for_status()
    file_data = response.content

    object_key = f"{uuid.uuid4().hex}.safetensors"
    file_size = len(file_data)
    file_hash = hashlib.sha256(file_data).hexdigest()

    storage = get_storage_service()
    storage_uri = _run_async(storage.save_lora_weights(file_data, object_key))

    gen_service = get_generation_service(db, user_id)
    gen_service.update_lora_weights(
        lora_id=lora_model_id,
        weights_object_key=object_key,
        lora_local_path=storage_uri,
        file_size=file_size,
        file_hash=file_hash,
    )

    logger.info(
        f"LoRA weights stored for model {lora_model_id}: "
        f"{file_size} bytes, hash={file_hash[:12]}..."
    )


def _collect_example_prompts(db: Session, lora_model_id: int, user_id: int) -> None:
    """Collect example prompts from source images and save to LoRA model."""
    from app.models.lora_model import LoraModel

    lora = db.query(LoraModel).filter(LoraModel.id == lora_model_id).first()
    if not lora:
        return

    # Get source image IDs
    source_image_ids: list[int] = []
    if lora.folder_id:
        from app.models.folder import FolderImage
        source_image_ids = [
            fi.image_id
            for fi in db.query(FolderImage).filter(FolderImage.folder_id == lora.folder_id).all()
        ]
    elif lora.cluster_id:
        from app.models.cluster import ClusterMembership
        source_image_ids = [
            cm.image_id
            for cm in db.query(ClusterMembership).filter(
                ClusterMembership.cluster_id == lora.cluster_id,
                ClusterMembership.is_excluded.is_(False),
            ).all()
        ]

    if not source_image_ids:
        return

    # Filter to images with descriptions
    image_service = get_image_service(db, user_id)
    candidates = []
    for img_id in source_image_ids:
        image = image_service.get_image(img_id)
        if image and image.image_metadata and image.image_metadata.description_long:
            candidates.append(image)

    if not candidates:
        return

    # Sample ~10% (min 3, max 10)
    sample_size = max(3, min(10, len(candidates) // 10 or 3))
    sample_size = min(sample_size, len(candidates))
    sampled = random.sample(candidates, sample_size)

    # Build prompts
    prompts = []
    for image in sampled:
        desc = image.image_metadata.description_long
        # Truncate long descriptions to keep prompts reasonable
        if len(desc) > 300:
            desc = desc[:297] + "..."
        prompts.append(f"{lora.trigger_word}, {desc}")

    lora.example_prompts = prompts
    db.commit()
    logger.info(f"Collected {len(prompts)} example prompts for LoRA model {lora_model_id}")


@celery_app.task(bind=True)
def download_lora_weights(self, lora_model_id: int, user_id: int | None = None) -> dict:
    """Download and store LoRA weights for an existing completed model."""
    db = _get_db()
    try:
        gen_service = get_generation_service(db, user_id)
        lora = gen_service.get_lora_model(lora_model_id)
        if not lora:
            return {"status": "error", "message": "LoRA model not found"}

        if lora.weights_object_key:
            return {"status": "skipped", "message": "Weights already downloaded"}

        if not lora.lora_url:
            return {"status": "error", "message": "No lora_url available for download"}

        _download_lora_weights(db, lora_model_id, lora.lora_url, user_id)
        return {"status": "success", "lora_model_id": lora_model_id}

    except Exception as e:
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to download LoRA weights for model {lora_model_id}: {err_msg}")
        return {"status": "error", "message": err_msg}
    finally:
        db.close()


@celery_app.task(bind=True)
def train_lora(self, lora_model_id: int, job_id: int | None = None, user_id: int | None = None) -> dict:
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
        user_id=user_id,
    )
    task_start = time.monotonic()
    db = _get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        gen_service = get_generation_service(db, user_id)
        lora = gen_service.get_lora_model(lora_model_id)
        if not lora:
            return {"status": "error", "message": "LoRA model not found"}

        # Check if this is a resume (LoRA already submitted to fal.ai)
        existing_request_id = None
        if lora.status == LoraModelStatus.TRAINING and lora.provider_metadata:
            existing_request_id = lora.provider_metadata.get("request_id")

        if existing_request_id:
            logger.info(f"Resuming training poll for LoRA {lora_model_id}, request_id={existing_request_id}")
            request_id = existing_request_id
            trainer = get_trainer(lora.training_provider, db=db, base_model=lora.base_model, user_id=user_id)
        else:
            # Update status to training
            gen_service.update_lora_status(lora_model_id, LoraModelStatus.TRAINING)

            # Load source images (folder or cluster)
            image_service = get_image_service(db, user_id)

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
                        ClusterMembership.is_excluded.is_(False),
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

            # Get model config to determine ZIP requirements and param names
            from app.providers.fal_provider import FAL_MODEL_CONFIG
            model_config = FAL_MODEL_CONFIG.get(lora.base_model, FAL_MODEL_CONFIG["flux-dev"])
            requires_zip = not model_config["supports_base64"]
            zip_param_name = model_config["zip_param"]

            # Instantiate trainer early so _ensure_fal_key() sets FAL_KEY
            # before any fal_client calls (e.g. upload)
            trainer = get_trainer(lora.training_provider, db=db, base_model=lora.base_model, user_id=user_id)

            trainer_kwargs = {}

            # Pass learning_rate from training_config if present
            if "learning_rate" in training_config:
                trainer_kwargs["learning_rate"] = training_config["learning_rate"]

            if use_captions or requires_zip:
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

                        if use_captions:
                            # Build caption from trigger word + tags/description
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
                        elif requires_zip:
                            # ZIP-only model without captions: use trigger word as caption
                            zf.writestr(f"{prefix}.txt", lora.trigger_word)

                        image_count += 1

                if image_count == 0:
                    raise Exception("No image data could be loaded from source")

                logger.info(f"Created ZIP with {image_count} images for LoRA training (captions={use_captions})")

                # Upload ZIP to fal CDN
                import fal_client
                zip_bytes = zip_buffer.getvalue()
                zip_url = fal_client.upload(zip_bytes, "application/zip")
                logger.info(f"Uploaded training ZIP ({len(zip_bytes)} bytes) to fal CDN")

                # Use the correct ZIP param name for the model
                trainer_kwargs[zip_param_name] = zip_url
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

            # Store request_id immediately so we can recover if worker dies during polling
            gen_service.update_lora_status(
                lora_model_id, LoraModelStatus.TRAINING,
                provider_metadata={"request_id": request_id, "base_model": lora.base_model},
            )

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

        # Best-effort download of weights — training already succeeded
        try:
            _download_lora_weights(db, lora_model_id, result.lora_url, user_id)
        except Exception as dl_err:
            logger.warning(f"Failed to download LoRA weights after training (model {lora_model_id}): {dl_err}")

        # Best-effort collection of example prompts from source images
        try:
            _collect_example_prompts(db, lora_model_id, user_id)
        except Exception as ep_err:
            logger.warning(f"Failed to collect example prompts for model {lora_model_id}: {ep_err}")

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(
            category=LogCategory.TASK,
            message=f"Task train_lora completed for lora_model {lora_model_id} in {elapsed:.0f}ms",
            task_name="train_lora",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
            user_id=user_id,
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
            user_id=user_id,
        )
        gen_service = get_generation_service(db, user_id)
        gen_service.update_lora_status(lora_model_id, LoraModelStatus.FAILED, err_msg)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        raise
    finally:
        db.close()


@celery_app.task(bind=True)
def generate_image(self, generated_image_id: int, job_id: int | None = None, user_id: int | None = None) -> dict:
    """
    Generate a single image via fal.ai.
    """
    write_log(
        category=LogCategory.TASK,
        message=f"Task generate_image started for generated_image {generated_image_id}",
        task_name="generate_image",
        job_id=job_id,
        user_id=user_id,
    )
    task_start = time.monotonic()
    db = _get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        gen_service = get_generation_service(db, user_id)
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
        generator = get_generator(gen.generation_provider, db=db, base_model=gen.base_model, user_id=user_id)
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
            user_id=user_id,
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
            user_id=user_id,
        )
        # Mark as failed
        gen = db.query(GeneratedImage).filter(GeneratedImage.id == generated_image_id).first()
        if gen:
            gen.status = GenerationStatus.FAILED
            gen.error_message = err_msg
            db.commit()
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        raise
    finally:
        db.close()


def _mark_generated_images_cancelled(db: Session, generated_image_ids: list[int]) -> None:
    """Mark pending/generating images as failed due to cancellation."""
    db.query(GeneratedImage).filter(
        GeneratedImage.id.in_(generated_image_ids),
        GeneratedImage.status.in_([GenerationStatus.PENDING, GenerationStatus.GENERATING]),
    ).update(
        {
            GeneratedImage.status: GenerationStatus.FAILED,
            GeneratedImage.error_message: "Cancelled by user",
        },
        synchronize_session="fetch",
    )
    db.commit()


@celery_app.task(bind=True)
def batch_generate(self, generated_image_ids: list[int], job_id: int | None = None, user_id: int | None = None) -> dict:
    """
    Generate multiple images. Dispatches individual generate_image tasks and polls for completion.
    """
    write_log(
        category=LogCategory.TASK,
        message=f"Task batch_generate started ({len(generated_image_ids)} images)",
        task_name="batch_generate",
        job_id=job_id,
        user_id=user_id,
    )
    task_start = time.monotonic()
    db = _get_db()
    try:
        job = db.query(Job).filter(Job.id == job_id).first() if job_id else None

        if job and job.status == JobStatus.CANCELLED:
            _mark_generated_images_cancelled(db, generated_image_ids)
            return {"status": "cancelled", "total": len(generated_image_ids)}

        if job:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            job.total_items = len(generated_image_ids)
            db.commit()

        # Dispatch individual tasks
        for gen_id in generated_image_ids:
            generate_image.delay(gen_id, user_id=user_id)

        # Poll for completion
        poll_interval = 5
        while True:
            db.expire_all()
            if job_id:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job and job.status == JobStatus.CANCELLED:
                    _mark_generated_images_cancelled(db, generated_image_ids)
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
            user_id=user_id,
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
            user_id=user_id,
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


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def _normalize_embedding_similarity(cosine_sim: float) -> float:
    """Normalize cosine similarity to 0-10 scale.

    Text embedding cosine similarity for same-described images typically
    falls in the 0.5-0.95 range.  A linear `*10` mapping makes everything
    look great (0.7 → 7.0).  Instead, stretch 0.5-0.95 across 0-10.
    """
    lower = 0.5
    upper = 0.95
    normalized = (cosine_sim - lower) / (upper - lower) * 10
    return max(0.0, min(10.0, normalized))


@celery_app.task(bind=True)
def evaluate_lora(self, evaluation_id: int, job_id: int | None = None, user_id: int | None = None) -> dict:
    """
    Evaluate a LoRA model by generating images from training set descriptions
    and comparing against originals, plus optional creative prompt evaluation.

    1. Load LoraEvaluation, validate LoRA model
    2. Sample N random images from source (folder/cluster)
    3. For each: generate using description, score pair (reference pairs)
    4. If creative_count > 0: generate novel prompts, generate + score (creative pairs)
    5. Generate AI assessment summary
    6. Aggregate scores
    """
    write_log(
        category=LogCategory.TASK,
        message=f"Task evaluate_lora started for evaluation {evaluation_id}",
        task_name="evaluate_lora",
        job_id=job_id,
        user_id=user_id,
    )
    task_start = time.monotonic()
    db = _get_db()
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        eval_service = get_evaluation_service(db, user_id)
        gen_service = get_generation_service(db, user_id)
        image_service = get_image_service(db, user_id)

        evaluation = eval_service.get_evaluation(evaluation_id)
        if not evaluation:
            return {"status": "error", "message": "Evaluation not found"}

        lora = gen_service.get_lora_model(evaluation.lora_model_id)
        if not lora:
            raise Exception("LoRA model not found")
        if lora.status != LoraModelStatus.COMPLETED or not lora.lora_url:
            raise Exception("LoRA model is not completed or has no URL")

        # Mark evaluation RUNNING
        eval_service.update_evaluation_status(evaluation_id, EvaluationStatus.RUNNING)

        config = evaluation.config or {}
        metrics_enabled = config.get("metrics_enabled", ["embedding_similarity"])
        gen_params = config.get("generation_params", {})
        vision_eval_provider = config.get("vision_eval_provider")
        creative_count = config.get("creative_count", 0)

        # Load source images from folder/cluster
        if lora.folder_id:
            from app.models.folder import FolderImage
            source_image_ids = [
                fi.image_id
                for fi in db.query(FolderImage).filter(FolderImage.folder_id == lora.folder_id).all()
            ]
        elif lora.cluster_id:
            from app.models.cluster import ClusterMembership
            source_image_ids = [
                cm.image_id
                for cm in db.query(ClusterMembership).filter(
                    ClusterMembership.cluster_id == lora.cluster_id,
                    ClusterMembership.is_excluded.is_(False),
                ).all()
            ]
        else:
            raise Exception("LoRA model has no associated folder or cluster")

        # Filter to images with descriptions
        candidate_images = []
        for img_id in source_image_ids:
            image = image_service.get_image(img_id)
            if image and image.image_metadata and image.image_metadata.description_long:
                candidate_images.append(image)

        if not candidate_images:
            raise Exception("No source images with descriptions found")

        # Sample for reference pairs
        sample_count = min(evaluation.sample_count, len(candidate_images))
        sampled = random.sample(candidate_images, sample_count)

        total_items = sample_count + creative_count

        # Update job total
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.total_items = total_items
                db.commit()

        # Get generator
        generator = get_generator(db=db, base_model=lora.base_model, user_id=user_id)

        # Get evaluator (used for both vision_eval and creative eval)
        evaluator = None
        if "vision_eval" in metrics_enabled or creative_count > 0:
            evaluator = get_evaluator(provider=vision_eval_provider, db=db, user_id=user_id)

        # Get embedder + describer for embedding similarity
        embedder = None
        describer = None
        if "embedding_similarity" in metrics_enabled:
            embedder = get_embedder(db=db, user_id=user_id)
            describer = get_describer(db=db, user_id=user_id)

        progress_idx = 0

        # ========== PHASE 1: Reference pairs ==========
        for idx, image in enumerate(sampled):
            pair = None
            try:
                description = image.image_metadata.description_long
                prompt = f"{lora.trigger_word}, {description}"

                # Create pair record
                pair = eval_service.create_pair(
                    evaluation_id=evaluation_id,
                    original_image_id=image.id,
                    prompt_used=prompt,
                    pair_type="reference",
                )
                eval_service.update_pair_status(pair.id, "generating")

                # Generate image
                gen_width = gen_params.get("width", image.width or 1024)
                gen_height = gen_params.get("height", image.height or 1024)

                result = _run_async(
                    generator.generate(
                        prompt=prompt,
                        width=gen_width,
                        height=gen_height,
                        num_inference_steps=gen_params.get("num_inference_steps", 28),
                        guidance_scale=gen_params.get("guidance_scale", 3.5),
                        lora_url=lora.lora_url,
                        lora_scale=gen_params.get("lora_scale", 1.0),
                    )
                )

                # Save generated image
                object_key = f"eval_{uuid.uuid4().hex}.png"
                thumbnails = _run_async(
                    eval_service.save_eval_generated_image(result.image_data, object_key)
                )

                eval_service.update_pair_generated(
                    pair.id,
                    object_key=object_key,
                    width=result.width,
                    height=result.height,
                    thumbnail_small=thumbnails.get("200"),
                    thumbnail_medium=thumbnails.get("400"),
                )

                # Score
                eval_service.update_pair_status(pair.id, "scoring")

                embedding_sim = None
                vision_score = None
                vision_assessment = None
                metrics_detail = None

                # Embedding similarity: describe generated → embed → compare
                if embedder and describer:
                    try:
                        desc_result = _run_async(
                            describer.describe_image(
                                result.image_data, "image/png",
                                description_prompt="Describe this image in detail for comparison purposes. Return JSON with a 'description' field.",
                            )
                        )
                        gen_text = desc_result.description

                        embed_result = _run_async(embedder.embed_text(gen_text))
                        gen_embedding = embed_result.embedding

                        original_embedding = image.image_metadata.embedding
                        if original_embedding is not None and len(original_embedding) > 0:
                            raw_sim = _cosine_similarity(
                                list(original_embedding), gen_embedding
                            )
                            embedding_sim = _normalize_embedding_similarity(raw_sim)
                    except Exception as e:
                        logger.warning(f"Embedding similarity failed for pair {pair.id}: {e}")

                # Vision AI evaluation
                if evaluator and "vision_eval" in metrics_enabled:
                    try:
                        original_data = _run_async(image_service.get_image_data(image.id))
                        if original_data:
                            eval_result = _run_async(
                                evaluator.evaluate_pair(
                                    original_image_data=original_data,
                                    generated_image_data=result.image_data,
                                    original_mime=image.mime_type or "image/jpeg",
                                    generated_mime="image/png",
                                    prompt_used=prompt,
                                )
                            )
                            vision_score = eval_result.overall
                            vision_assessment = eval_result.assessment
                            metrics_detail = {
                                "style_fidelity": eval_result.style_fidelity,
                                "subject_accuracy": eval_result.subject_accuracy,
                                "detail_preservation": eval_result.detail_preservation,
                            }
                    except Exception as e:
                        logger.warning(f"Vision eval failed for pair {pair.id}: {e}")

                # Compute combined pair_score
                scores = []
                weights = []
                if vision_score is not None:
                    scores.append(vision_score)
                    weights.append(0.7)
                if embedding_sim is not None:
                    scores.append(embedding_sim)
                    weights.append(0.3)

                pair_score = None
                if scores:
                    total_weight = sum(weights)
                    pair_score = sum(s * w for s, w in zip(scores, weights)) / total_weight

                eval_service.update_pair_scores(
                    pair.id,
                    embedding_similarity=embedding_sim,
                    vision_score=vision_score,
                    vision_assessment=vision_assessment,
                    pair_score=pair_score,
                    metrics_detail=metrics_detail,
                )
                eval_service.update_pair_status(pair.id, "completed")

                progress_idx += 1
                if job_id:
                    job = db.query(Job).filter(Job.id == job_id).first()
                    if job:
                        job.progress = progress_idx
                        db.commit()

            except Exception as e:
                err_msg = _unwrap_error(e)
                logger.error(f"Failed to process reference pair for image {image.id}: {err_msg}")
                if pair:
                    eval_service.update_pair_status(pair.id, "failed", err_msg)
                progress_idx += 1

        # ========== PHASE 2: Creative pairs ==========
        if creative_count > 0 and evaluator:
            try:
                # Collect sample descriptions for prompt generation
                sample_descriptions = [
                    img.image_metadata.description_long
                    for img in candidate_images
                    if img.image_metadata and img.image_metadata.description_long
                ]

                # Generate creative prompts
                creative_prompts = _run_async(
                    evaluator.generate_creative_prompts(
                        trigger_word=lora.trigger_word,
                        sample_descriptions=sample_descriptions,
                        count=creative_count,
                    )
                )
                logger.info(f"Generated {len(creative_prompts)} creative prompts")

                for c_idx, creative_prompt in enumerate(creative_prompts):
                    pair = None
                    try:
                        pair = eval_service.create_pair(
                            evaluation_id=evaluation_id,
                            original_image_id=None,
                            prompt_used=creative_prompt,
                            pair_type="creative",
                        )
                        eval_service.update_pair_status(pair.id, "generating")

                        # Generate image
                        c_width = gen_params.get("width", 1024)
                        c_height = gen_params.get("height", 1024)

                        result = _run_async(
                            generator.generate(
                                prompt=creative_prompt,
                                width=c_width,
                                height=c_height,
                                num_inference_steps=gen_params.get("num_inference_steps", 28),
                                guidance_scale=gen_params.get("guidance_scale", 3.5),
                                lora_url=lora.lora_url,
                                lora_scale=gen_params.get("lora_scale", 1.0),
                            )
                        )

                        # Save generated image
                        object_key = f"eval_creative_{uuid.uuid4().hex}.png"
                        thumbnails = _run_async(
                            eval_service.save_eval_generated_image(result.image_data, object_key)
                        )

                        eval_service.update_pair_generated(
                            pair.id,
                            object_key=object_key,
                            width=result.width,
                            height=result.height,
                            thumbnail_small=thumbnails.get("200"),
                            thumbnail_medium=thumbnails.get("400"),
                        )

                        # Score with single-image evaluation (no reference comparison)
                        eval_service.update_pair_status(pair.id, "scoring")

                        eval_result = _run_async(
                            evaluator.evaluate_single(
                                image_data=result.image_data,
                                mime_type="image/png",
                                prompt_used=creative_prompt,
                            )
                        )

                        vision_score = eval_result.overall
                        vision_assessment = eval_result.assessment
                        metrics_detail = {
                            "realism": eval_result.style_fidelity,
                            "prompt_adherence": eval_result.subject_accuracy,
                            "detail_quality": eval_result.detail_preservation,
                            "pair_type": "creative",
                        }

                        eval_service.update_pair_scores(
                            pair.id,
                            vision_score=vision_score,
                            vision_assessment=vision_assessment,
                            pair_score=vision_score,
                            metrics_detail=metrics_detail,
                        )
                        eval_service.update_pair_status(pair.id, "completed")

                    except Exception as e:
                        err_msg = _unwrap_error(e)
                        logger.error(f"Failed to process creative pair {c_idx}: {err_msg}")
                        if pair:
                            eval_service.update_pair_status(pair.id, "failed", err_msg)

                    progress_idx += 1
                    if job_id:
                        job = db.query(Job).filter(Job.id == job_id).first()
                        if job:
                            job.progress = progress_idx
                            db.commit()

            except Exception as e:
                logger.error(f"Creative prompt generation failed: {_unwrap_error(e)}")

        # ========== PHASE 3: Aggregate scores ==========
        db.expire_all()
        evaluation = eval_service.get_evaluation(evaluation_id)
        pairs = evaluation.pairs if evaluation else []

        completed = [p for p in pairs if p.status == "completed"]
        ref_completed = [p for p in completed if p.pair_type == "reference"]
        creative_completed = [p for p in completed if p.pair_type == "creative"]

        avg_embedding = None
        avg_vision = None
        overall = None

        if ref_completed:
            emb_scores = [p.embedding_similarity for p in ref_completed if p.embedding_similarity is not None]
            vis_scores = [p.vision_score for p in ref_completed if p.vision_score is not None]
            pair_scores = [p.pair_score for p in ref_completed if p.pair_score is not None]

            if emb_scores:
                avg_embedding = sum(emb_scores) / len(emb_scores)
            if vis_scores:
                avg_vision = sum(vis_scores) / len(vis_scores)
            if pair_scores:
                overall = sum(pair_scores) / len(pair_scores)

        # Creative scores summary
        creative_section = ""
        avg_creative_score = None
        if creative_completed:
            creative_scores = [p.vision_score for p in creative_completed if p.vision_score is not None]
            if creative_scores:
                avg_creative_score = sum(creative_scores) / len(creative_scores)
                creative_section = (
                    f"\n## Creative/Generalization Test\n"
                    f"{len(creative_completed)} creative prompts were generated and evaluated.\n"
                    f"Average creative score: {avg_creative_score:.1f}/10\n"
                )

        # ========== PHASE 4: AI Assessment Summary ==========
        assessment_summary = None
        if evaluator:
            try:
                pair_assessments = []
                for p in completed:
                    if p.vision_assessment:
                        pair_assessments.append({
                            "score": f"{p.pair_score:.1f}" if p.pair_score is not None else "N/A",
                            "assessment": p.vision_assessment,
                            "type": p.pair_type,
                        })

                if pair_assessments:
                    assessment_summary = _run_async(
                        evaluator.summarize_assessments(
                            model_name=lora.name,
                            trigger_word=lora.trigger_word,
                            pair_assessments=pair_assessments,
                            overall_score=overall,
                            avg_vision=avg_vision,
                            avg_embedding=avg_embedding,
                            creative_section=creative_section,
                        )
                    )
            except Exception as e:
                logger.warning(f"Assessment summary generation failed: {e}")
                # Fallback: concatenate
                assessments = [p.vision_assessment for p in completed if p.vision_assessment]
                assessment_summary = " | ".join(assessments) if assessments else None

        aggregate_results = {
            "total_pairs": len(pairs),
            "completed_pairs": len(completed),
            "failed_pairs": len([p for p in pairs if p.status == "failed"]),
            "reference_pairs": len(ref_completed),
            "creative_pairs": len(creative_completed),
            "avg_creative_score": avg_creative_score,
            "score_weights": {"vision": 0.7, "embedding": 0.3},
        }

        eval_service.update_evaluation_status(
            evaluation_id,
            EvaluationStatus.COMPLETED,
            overall_score=overall,
            avg_embedding_similarity=avg_embedding,
            avg_vision_score=avg_vision,
            assessment_summary=assessment_summary,
            aggregate_results=aggregate_results,
        )

        _update_job_status(
            db, job_id, JobStatus.COMPLETED,
            progress=total_items,
            result={
                "overall_score": overall,
                "completed_pairs": len(completed),
                "failed_pairs": len([p for p in pairs if p.status == "failed"]),
                "creative_pairs": len(creative_completed),
                "avg_creative_score": avg_creative_score,
            },
        )

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(
            category=LogCategory.TASK,
            message=f"Task evaluate_lora completed for evaluation {evaluation_id} in {elapsed:.0f}ms (score={overall})",
            task_name="evaluate_lora",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
            user_id=user_id,
        )
        return {
            "status": "success",
            "evaluation_id": evaluation_id,
            "overall_score": overall,
            "completed_pairs": len(completed),
            "creative_pairs": len(creative_completed),
        }

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        err_msg = _unwrap_error(e)
        logger.error(f"Failed to evaluate LoRA (evaluation {evaluation_id}): {err_msg}")
        write_log(
            category=LogCategory.TASK,
            message=f"Task evaluate_lora failed for evaluation {evaluation_id}: {err_msg}",
            level=LogLevel.ERROR,
            task_name="evaluate_lora",
            job_id=job_id,
            duration_ms=round(elapsed, 1),
            extra={"error": err_msg},
            user_id=user_id,
        )
        eval_service = get_evaluation_service(db, user_id)
        eval_service.update_evaluation_status(evaluation_id, EvaluationStatus.FAILED, error_message=err_msg)
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=err_msg)
        raise
    finally:
        db.close()
