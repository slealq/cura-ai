"""Celery tasks for the image processing pipeline."""
import asyncio
import logging
import threading
import time
from datetime import datetime

import numpy as np
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models import Image, ImageStatus, Job, JobStatus
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers import get_cluster_summarizer, get_describer, get_embedder, get_tagger
from app.services.billing_context import (
    clear_last_api_call_tokens,
    get_last_api_call_tokens,
    get_trace_id,
    init_trace,
    is_billing_deferred,
    make_idempotency_key,
    set_billing_deferred,
    set_billing_image,
    set_billing_job,
    set_billing_user,
    set_session_id,
    set_trace_id,
)
from app.services.billing_orchestrator import ORCHESTRATOR_ENABLED_OPS, BillingOrchestrator
from app.services.billing_service import InsufficientBalanceError, ZeroCostEstimateError, finalize_job_billing
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
from app.workers.dispatch import dispatch

logger = logging.getLogger(__name__)

# Per-thread event loop kept alive so async clients (httpx inside OpenAI/Anthropic
# SDKs) can schedule cleanup callbacks without hitting "Event loop is closed".
_thread_local = threading.local()


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
    """Run async function in sync context (works in thread-pool workers).

    Uses a per-thread event loop that stays open across calls so that async
    HTTP clients (httpx inside OpenAI/Anthropic SDKs) can clean up their
    connection pools without hitting 'Event loop is closed'.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — use a persistent per-thread loop
        loop = getattr(_thread_local, 'loop', None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            _thread_local.loop = loop
        try:
            return loop.run_until_complete(coro)
        except Exception as e:
            return _unwrap_retry_success(e)
    # There IS a running loop (shouldn't happen in Celery thread-pool, but
    # handle defensively) — create a throwaway loop.
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(coro)
    except Exception as e:
        return _unwrap_retry_success(e)
    finally:
        new_loop.close()


def _unwrap_retry_success(e: Exception):
    """Handle tenacity RetryError that wraps a *successful* last attempt.

    tenacity 9.x can raise RetryError even when the final retry succeeded
    (the Future shows state=finished with a returned value). Extract the
    successful result instead of propagating the error.
    """
    if hasattr(e, 'last_attempt'):
        fut = e.last_attempt
        if not fut.failed:
            logger.warning("tenacity RetryError wrapping a successful result — extracting it")
            return fut.result()
    raise e


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
        if job.created_at:
            queue_wait_ms = (job.started_at - job.created_at).total_seconds() * 1000
            logger.info(
                f"Job {job_id} started after {queue_wait_ms:.0f}ms in queue",
                extra={"event_type": "queue_wait", "queue_wait_ms": queue_wait_ms, "job_id": job_id, "job_type": job.job_type.value if job.job_type else None},
            )
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

    Idempotent: safe to call multiple times (uses get-or-create for folder).
    """
    params = job.parameters or {}
    folder_id = params.get("folder_id")
    new_folder_name = params.get("new_folder_name")
    all_upload_ids = list(set((job.result or {}).get("all_upload_ids", [])))

    if not (folder_id or new_folder_name) or not all_upload_ids:
        return

    try:
        from app.models.folder import Folder
        from app.services.folder_service import get_folder_service
        folder_service = get_folder_service(db, job.user_id)

        if new_folder_name:
            # Get-or-create: look up existing folder first to handle race conditions
            # where both API and Celery worker trigger this concurrently.
            existing = (
                db.query(Folder)
                .filter(Folder.name == new_folder_name, Folder.user_id == job.user_id)
                .first()
            )
            if existing:
                folder_id = existing.id
            else:
                try:
                    folder = folder_service.create_folder(new_folder_name)
                    folder_id = folder.id
                except Exception:
                    # Another caller may have created it between our check and insert
                    db.rollback()
                    existing = (
                        db.query(Folder)
                        .filter(Folder.name == new_folder_name, Folder.user_id == job.user_id)
                        .first()
                    )
                    if existing:
                        folder_id = existing.id
                    else:
                        raise

        if folder_id:
            folder_service.add_images_to_folder(folder_id, all_upload_ids)
            folder_service.refresh_cover_image(folder_id)
            folder_service.generate_cover_composite(folder_id)
            logger.info(f"Deferred folder assignment: added {len(all_upload_ids)} images to folder {folder_id} for job {job.id}")
    except Exception as e:
        logger.error(f"Failed deferred folder assignment for job {job.id}: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def _init_task_context(user_id, job_id=None, image_id=None, trace_id=None, session_id=None):
    """Initialize billing and trace context for a Celery task."""
    set_billing_user(user_id)
    if job_id is not None:
        set_billing_job(job_id)
    if image_id is not None:
        set_billing_image(image_id)
    if trace_id:
        set_trace_id(trace_id)
    else:
        init_trace()
    if session_id:
        set_session_id(session_id)

    # Sentry trace continuation is handled by _start_worker_trace in
    # celery_app.py (task_prerun signal). Here we just set Sentry tags.
    try:
        import sentry_sdk
        sentry_sdk.set_tag("app.trace_id", get_trace_id())
        if job_id is not None:
            sentry_sdk.set_tag("app.job_id", str(job_id))
        sentry_sdk.set_tag("app.user_id", str(user_id))
    except Exception:
        pass


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
        if not job or not job.total_items or job.progress < job.total_items:
            return

        # Skip if job already completed (API path may have completed it first)
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            # Job already finalized — still try folder assignment in case it
            # was skipped or failed on the first attempt (idempotent).
            _assign_folder_on_completion(db, job)
            return

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
        job.result = {**(job.result or {}), "processing_done_at": datetime.utcnow().isoformat()}
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
    except Exception as e:
        logger.error(f"Failed to finalize ingest job {job_id}: {e}")


@celery_app.task(bind=True)
def process_ingest(self, image_id: int, user_id: int, job_id: int | None = None, trace_id: str | None = None, session_id: str | None = None) -> dict:
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
def process_ingest_batch(
    self, image_ids: list[int], user_id: int, job_id: int | None = None,
    trace_id: str | None = None, session_id: str | None = None,
) -> dict:
    """
    Process a batch of fast-ingested images in a single task.

    One DB session for the whole batch. For each image: reads file from storage,
    generates thumbnails, conditionally computes metadata (skipped if already
    populated by fast_ingest), and updates the record to INGESTED.

    Error isolation: if one image fails, it is marked FAILED and the rest continue.
    Re-delivery guard: images already past PENDING status are skipped.
    """
    write_log(
        category=LogCategory.TASK,
        message=f"Task process_ingest_batch started for {len(image_ids)} images",
        task_name="process_ingest_batch",
        job_id=job_id,
        user_id=user_id,
    )
    batch_start = time.monotonic()
    db = get_db()
    results = []

    try:
        from app.services.storage import get_storage_service

        storage = get_storage_service()

        for image_id in image_ids:
            task_start = time.monotonic()
            try:
                image = (
                    db.query(Image)
                    .filter(Image.id == image_id, Image.user_id == user_id)
                    .first()
                )
                if not image:
                    logger.warning(f"Batch ingest: image {image_id} not found, skipping")
                    _finish_ingest_job_item(db, job_id, failed=True)
                    results.append({"image_id": image_id, "status": "not_found"})
                    continue

                # Re-delivery guard: skip images already past PENDING
                if image.status != ImageStatus.PENDING:
                    logger.info(
                        f"Batch ingest: image {image_id} already {image.status.value}, skipping"
                    )
                    _finish_ingest_job_item(db, job_id, failed=False)
                    results.append({"image_id": image_id, "status": "skipped"})
                    continue

                # Read file from storage
                file_data = run_async(storage.get_image(image.object_key))

                # Only compute metadata if fast_ingest didn't populate it (Tier 3)
                if image.width is None or image.height is None:
                    mime_type, width, height, perceptual_hash = (
                        storage.compute_image_metadata(file_data)
                    )
                    image.mime_type = mime_type
                    image.width = width
                    image.height = height
                    image.perceptual_hash = perceptual_hash

                # Generate thumbnails
                thumbnails = run_async(
                    storage.generate_thumbnails(file_data, image.object_key)
                )

                image.thumbnail_uri_small = thumbnails.get("200")
                image.thumbnail_uri_medium = thumbnails.get("400")
                image.thumbnail_uri_large = thumbnails.get("800")
                image.status = ImageStatus.INGESTED
                image.ingested_at = datetime.utcnow()
                image.error_message = None
                db.commit()

                _finish_ingest_job_item(db, job_id, failed=False)

                elapsed = (time.monotonic() - task_start) * 1000
                results.append({
                    "image_id": image_id,
                    "status": "success",
                    "width": image.width,
                    "height": image.height,
                    "ms": round(elapsed, 1),
                })

            except Exception as e:
                elapsed = (time.monotonic() - task_start) * 1000
                err_msg = _unwrap_error(e)
                logger.error(
                    f"Batch ingest: failed image {image_id}: {err_msg}"
                )
                try:
                    image = db.query(Image).filter(Image.id == image_id).first()
                    if image:
                        image.status = ImageStatus.FAILED
                        image.error_message = err_msg
                        image.retry_count += 1
                        db.commit()
                except Exception:
                    pass
                _finish_ingest_job_item(db, job_id, failed=True)
                results.append({
                    "image_id": image_id,
                    "status": "failed",
                    "error": err_msg,
                })

        batch_elapsed = (time.monotonic() - batch_start) * 1000
        n_ok = sum(1 for r in results if r["status"] == "success")
        n_fail = sum(1 for r in results if r["status"] == "failed")
        write_log(
            category=LogCategory.TASK,
            message=(
                f"Task process_ingest_batch completed: {n_ok} ok, {n_fail} failed, "
                f"{len(image_ids)} total in {batch_elapsed:.0f}ms"
            ),
            task_name="process_ingest_batch",
            job_id=job_id,
            duration_ms=round(batch_elapsed, 1),
            user_id=user_id,
        )
        return {"status": "success", "results": results}

    finally:
        db.close()


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def tag_image(
    self, image_id: int, user_id: int, tag_prompt: str | None = None,
    job_id: int | None = None, provider: str | None = None, model: str | None = None,
    temperature: float | None = None, max_tokens_override: int | None = None,
    trace_id: str | None = None, session_id: str | None = None,
) -> dict:
    """
    Tag an image with categorization tags.

    Pipeline stage: 3
    """
    write_log(category=LogCategory.TASK, message=f"Task tag_image started for image {image_id}",
              task_name="tag_image", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, job_id=job_id, image_id=image_id, trace_id=trace_id, session_id=session_id)
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
        tagger = get_tagger(provider=provider, model=model, db=db, user_id=user_id, temperature=temperature, max_tokens_override=max_tokens_override)
        tag_start = time.monotonic()
        result = run_async(tagger.tag_image(image_data, image.mime_type, tag_prompt))
        tagging_duration_ms = round((time.monotonic() - tag_start) * 1000)

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            tags=result.tags,
            tagging_model=result.model,
            tagging_prompt_version=result.prompt_version,
            tag_prompt_text=tag_prompt,
            tagged_at=datetime.utcnow(),
            tagging_duration_ms=tagging_duration_ms,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.TAGGED)
        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1, result={"tags": result.tags})

        # Auto-chain: re-embed if description exists (embedding depends on tags)
        image = image_service.get_image(image_id)
        if image and image.image_metadata and image.image_metadata.description_long:
            dispatch(embed_image, image_id, user_id)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task tag_image completed for image {image_id} in {elapsed:.0f}ms ({len(result.tags)} tags)",
                  task_name="tag_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "image_id": image_id, "tags": result.tags}

    except InsufficientBalanceError:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message="Insufficient credits")
        return {"status": "error", "message": "Insufficient credits"}
    except ZeroCostEstimateError as e:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=f"Billing config error: {e}")
        return {"status": "error", "message": f"Billing config error: {e}"}
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
        set_trace_id(None)
        set_billing_image(None)
        set_billing_job(None)
        db.close()


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def describe_image(
    self, image_id: int, user_id: int, description_prompt: str | None = None,
    job_id: int | None = None, provider: str | None = None, model: str | None = None,
    temperature: float | None = None, max_tokens_override: int | None = None,
    trace_id: str | None = None, session_id: str | None = None,
) -> dict:
    """
    Generate a detailed description for an image.

    Pipeline stage: 4
    """
    write_log(category=LogCategory.TASK, message=f"Task describe_image started for image {image_id}",
              task_name="describe_image", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, job_id=job_id, image_id=image_id, trace_id=trace_id, session_id=session_id)
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
        describer = get_describer(provider=provider, model=model, db=db, user_id=user_id, temperature=temperature, max_tokens_override=max_tokens_override)
        desc_start = time.monotonic()
        result = run_async(describer.describe_image(image_data, image.mime_type, description_prompt))
        caption_duration_ms = round((time.monotonic() - desc_start) * 1000)

        # Save metadata
        image_service.save_metadata(
            image_id=image_id,
            description_long=result.description,
            caption_model=result.model,
            description_prompt_text=description_prompt,
            described_at=datetime.utcnow(),
            caption_duration_ms=caption_duration_ms,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.DESCRIBED)
        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1)

        # Auto-chain: re-embed if tags exist (embedding depends on description)
        image = image_service.get_image(image_id)
        if image and image.image_metadata and image.image_metadata.tags:
            dispatch(embed_image, image_id, user_id)

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task describe_image completed for image {image_id} in {elapsed:.0f}ms",
                  task_name="describe_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "image_id": image_id}

    except InsufficientBalanceError:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message="Insufficient credits")
        return {"status": "error", "message": "Insufficient credits"}
    except ZeroCostEstimateError as e:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=f"Billing config error: {e}")
        return {"status": "error", "message": f"Billing config error: {e}"}
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
        set_trace_id(None)
        set_billing_image(None)
        set_billing_job(None)
        db.close()


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def embed_image(self, image_id: int, user_id: int, job_id: int | None = None, trace_id: str | None = None, session_id: str | None = None) -> dict:
    """
    Generate embedding for an image based on its tags and description.

    Pipeline stage: 5
    """
    write_log(category=LogCategory.TASK, message=f"Task embed_image started for image {image_id}",
              task_name="embed_image", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, job_id=job_id, image_id=image_id, trace_id=trace_id, session_id=session_id)
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
        embed_start = time.monotonic()
        result = run_async(embedder.embed_text(text))
        embedding_duration_ms = round((time.monotonic() - embed_start) * 1000)

        # Save embedding
        image_service.save_metadata(
            image_id=image_id,
            embedding=result.embedding,
            embedding_model=result.model,
            embedded_at=datetime.utcnow(),
            embedding_duration_ms=embedding_duration_ms,
        )

        # Update status
        image_service.update_status(image_id, ImageStatus.EMBEDDED)
        _update_job_status(db, job_id, JobStatus.COMPLETED, progress=1, result={"dimensions": result.dimensions})

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK, message=f"Task embed_image completed for image {image_id} in {elapsed:.0f}ms",
                  task_name="embed_image", image_id=image_id, job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "image_id": image_id, "dimensions": result.dimensions}

    except InsufficientBalanceError:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message="Insufficient credits")
        return {"status": "error", "message": "Insufficient credits"}
    except ZeroCostEstimateError as e:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=f"Billing config error: {e}")
        return {"status": "error", "message": f"Billing config error: {e}"}
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
        set_trace_id(None)
        set_billing_image(None)
        set_billing_job(None)
        db.close()


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def tag_and_describe_image(
    self, image_id: int, user_id: int, tag_prompt: str | None = None, description_prompt: str | None = None,
    trace_id: str | None = None, session_id: str | None = None,
) -> dict:
    """
    Combined task to tag and describe an image.

    This is more efficient as it only loads the image once.
    """
    _init_task_context(user_id, image_id=image_id, trace_id=trace_id, session_id=session_id)
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
        set_trace_id(None)
        set_billing_image(None)
        db.close()


@celery_app.task(bind=True)
def cluster_all_images(self, user_id: int, job_id: int | None = None, trace_id: str | None = None, session_id: str | None = None) -> dict:
    """
    Cluster all embedded images.

    Pipeline stage: 6
    """
    write_log(category=LogCategory.TASK, message="Task cluster_all_images started",
              task_name="cluster_all_images", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, trace_id=trace_id, session_id=session_id)
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
            dispatch(summarize_clusters, cluster_ids, user_id)

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


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def summarize_cluster(self, cluster_id: int, user_id: int, job_id: int | None = None, trace_id: str | None = None, session_id: str | None = None) -> dict:
    """
    Generate AI summary for a cluster.

    Pipeline stage: 7
    """
    write_log(category=LogCategory.TASK, message=f"Task summarize_cluster started for cluster {cluster_id}",
              task_name="summarize_cluster", user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, trace_id=trace_id, session_id=session_id)
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

        # Resolve provider from settings (mirrors get_cluster_summarizer logic)
        _settings_svc = get_settings_service(db, user_id)
        _provider_config = _settings_svc.get_provider_config()
        _summ_provider = (
            _provider_config.get("language_provider")
            or _provider_config.get("vision_provider")
            or "openai"
        )

        orch = BillingOrchestrator(db, user_id) if "summarize" in ORCHESTRATOR_ENABLED_OPS else None
        decision = None
        if orch:
            idem_key = make_idempotency_key(user_id, get_trace_id(), "summarize", cluster_id)
            # Build a sample of descriptions for token estimation
            _sample_desc = "\n".join(descriptions[:5]) if descriptions else ""
            decision, is_new = orch.create_decision(
                operation="summarize",
                provider=_summ_provider,
                model=summarizer.get_model_name(),
                trace_id=get_trace_id(),
                idempotency_key=idem_key,
                resource_id=cluster_id,
                job_id=job_id,
                prompt_text=_sample_desc,
            )
            if not is_new:
                return {"status": "skipped", "cluster_id": cluster_id}

        try:
            result = run_async(
                summarizer.summarize_cluster(common_tags, descriptions, cluster.size)
            )
        except Exception as e:
            if orch and decision:
                orch.fail_decision(decision.id, str(e))
            raise

        if orch and decision:
            in_tok, out_tok, prov_cost = get_last_api_call_tokens()
            clear_last_api_call_tokens()
            orch.record_actual(
                decision.id,
                actual_input_tokens=in_tok,
                actual_output_tokens=out_tok,
                provider_cost=prov_cost,
                defer_debit=is_billing_deferred(),
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
        set_trace_id(None)
        db.close()


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def summarize_clusters(self, cluster_ids: list[int], user_id: int, job_id: int | None = None, trace_id: str | None = None, session_id: str | None = None) -> dict:
    """Summarize multiple clusters."""
    _init_task_context(user_id, job_id=job_id, trace_id=trace_id, session_id=session_id)
    db = get_db()
    try:
        if job_id:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job:
                job.status = JobStatus.RUNNING
                job.started_at = datetime.utcnow()
                job.total_items = len(cluster_ids)
                db.commit()

        set_billing_deferred(True)
        results = []
        for i, cluster_id in enumerate(cluster_ids):
            result = summarize_cluster(cluster_id, user_id, job_id=job_id)
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

        # Aggregate costs from all summarize calls onto the job
        try:
            finalize_job_billing(db, user_id, job_id, create_debit=True)
        except Exception:
            logger.warning(f"Failed to finalize billing for summarize job {job_id}", exc_info=True)

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
        set_trace_id(None)
        set_billing_job(None)
        db.close()


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def process_image_pipeline(
    self, image_id: int, user_id: int, tag_prompt: str | None = None,
    description_prompt: str | None = None, job_id: int | None = None,
    provider: str | None = None, model: str | None = None,
    temperature: float | None = None, max_tokens_tag: int | None = None,
    max_tokens_describe: int | None = None,
    trace_id: str | None = None, session_id: str | None = None,
) -> dict:
    """
    Run full pipeline for a single image: tag -> describe -> embed.

    Clusters are run separately after batch ingestion.
    """
    write_log(category=LogCategory.TASK, message=f"Task process_image_pipeline started for image {image_id}",
              task_name="process_image_pipeline", image_id=image_id, job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, job_id=job_id, image_id=image_id, trace_id=trace_id, session_id=session_id)
    # Only defer billing when we have a job_id — finalize_job_billing needs
    # job_id to aggregate deferred costs. Without it, inline debits are safer.
    if job_id:
        set_billing_deferred(True)
    db = get_db()
    image_filename = None
    try:
        _update_job_status(db, job_id, JobStatus.RUNNING)

        image_service = get_image_service(db, user_id)
        image = image_service.get_image(image_id)

        if not image:
            return {"status": "error", "message": "Image not found"}

        image_filename = image.original_filename

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
        tagger = get_tagger(provider=provider, model=model, db=db, user_id=user_id, temperature=temperature, max_tokens_override=max_tokens_tag)
        trace_id = get_trace_id()
        orch = BillingOrchestrator(db, user_id) if "tag" in ORCHESTRATOR_ENABLED_OPS else None

        if orch:
            idem_key = make_idempotency_key(user_id, trace_id, "tag", image_id)
            decision, is_new = orch.create_decision(
                operation="tag", provider=provider or "openai", model=tagger.get_model_name(),
                trace_id=trace_id, idempotency_key=idem_key,
                image_id=image_id, job_id=job_id,
                image_width=image.width, image_height=image.height,
                prompt_text=tag_prompt,
            )
            if not is_new:
                logger.info("Duplicate tag detected for image %s, skipping", image_id)
                # Still need tag_result for downstream — fetch from DB
                tag_result = type('R', (), {'tags': image.image_metadata.tags if image.image_metadata else [], 'model': tagger.get_model_name(), 'prompt_version': 'cached'})()
                tagging_duration_ms = 0
            else:
                try:
                    tag_start = time.monotonic()
                    tag_result = run_async(tagger.tag_image(image_data, image.mime_type, tag_prompt))
                    tagging_duration_ms = round((time.monotonic() - tag_start) * 1000)
                    in_tok, out_tok, prov_cost = get_last_api_call_tokens()
                    clear_last_api_call_tokens()
                    orch.record_actual(
                        decision.id, actual_input_tokens=in_tok,
                        actual_output_tokens=out_tok, provider_cost=prov_cost,
                        defer_debit=is_billing_deferred(),
                    )
                except Exception as e:
                    orch.fail_decision(decision.id, str(e))
                    raise
        else:
            tag_start = time.monotonic()
            tag_result = run_async(tagger.tag_image(image_data, image.mime_type, tag_prompt))
            tagging_duration_ms = round((time.monotonic() - tag_start) * 1000)

        # Describe
        describer = get_describer(provider=provider, model=model, db=db, user_id=user_id, temperature=temperature, max_tokens_override=max_tokens_describe)
        orch_desc = BillingOrchestrator(db, user_id) if "describe" in ORCHESTRATOR_ENABLED_OPS else None

        if orch_desc:
            idem_key = make_idempotency_key(user_id, trace_id, "describe", image_id)
            decision, is_new = orch_desc.create_decision(
                operation="describe", provider=provider or "openai", model=describer.get_model_name(),
                trace_id=trace_id, idempotency_key=idem_key,
                image_id=image_id, job_id=job_id,
                image_width=image.width, image_height=image.height,
                prompt_text=description_prompt,
            )
            if not is_new:
                logger.info("Duplicate describe detected for image %s, skipping", image_id)
                description_result = type('R', (), {'description': image.image_metadata.description_long if image.image_metadata else '', 'model': describer.get_model_name()})()
                caption_duration_ms = 0
            else:
                try:
                    desc_start = time.monotonic()
                    description_result = run_async(describer.describe_image(image_data, image.mime_type, description_prompt))
                    caption_duration_ms = round((time.monotonic() - desc_start) * 1000)
                    in_tok, out_tok, prov_cost = get_last_api_call_tokens()
                    clear_last_api_call_tokens()
                    orch_desc.record_actual(
                        decision.id, actual_input_tokens=in_tok,
                        actual_output_tokens=out_tok, provider_cost=prov_cost,
                        defer_debit=is_billing_deferred(),
                    )
                except Exception as e:
                    orch_desc.fail_decision(decision.id, str(e))
                    raise
        else:
            desc_start = time.monotonic()
            description_result = run_async(describer.describe_image(image_data, image.mime_type, description_prompt))
            caption_duration_ms = round((time.monotonic() - desc_start) * 1000)

        # Build text for embedding
        text_parts = []
        if tag_result.tags:
            text_parts.append("Tags: " + ", ".join(tag_result.tags))
        text_parts.append(description_result.description)
        text = "\n".join(text_parts)

        # Embed
        embedder = get_embedder(db=db, user_id=user_id)
        orch_embed = BillingOrchestrator(db, user_id) if "embed" in ORCHESTRATOR_ENABLED_OPS else None

        if orch_embed:
            idem_key = make_idempotency_key(user_id, trace_id, "embed", image_id)
            decision, is_new = orch_embed.create_decision(
                operation="embed", provider="openai", model=embedder.get_model_name(),
                trace_id=trace_id, idempotency_key=idem_key,
                image_id=image_id, job_id=job_id,
                tags=tag_result.tags,
                description=description_result.description,
            )
            if not is_new:
                logger.info("Duplicate embed detected for image %s, skipping", image_id)
                embed_result = type('R', (), {'embedding': image.image_metadata.embedding if image.image_metadata else [], 'model': embedder.get_model_name(), 'dimensions': 1536})()
                embedding_duration_ms = 0
            else:
                try:
                    embed_start_t = time.monotonic()
                    embed_result = run_async(embedder.embed_text(text))
                    embedding_duration_ms = round((time.monotonic() - embed_start_t) * 1000)
                    in_tok, out_tok, prov_cost = get_last_api_call_tokens()
                    clear_last_api_call_tokens()
                    orch_embed.record_actual(
                        decision.id, actual_input_tokens=in_tok,
                        actual_output_tokens=out_tok, provider_cost=prov_cost,
                        defer_debit=is_billing_deferred(),
                    )
                except Exception as e:
                    orch_embed.fail_decision(decision.id, str(e))
                    raise
        else:
            embed_start_t = time.monotonic()
            embed_result = run_async(embedder.embed_text(text))
            embedding_duration_ms = round((time.monotonic() - embed_start_t) * 1000)

        now = datetime.utcnow()

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
            tag_prompt_text=tag_prompt,
            description_prompt_text=description_prompt,
            tagged_at=now,
            described_at=now,
            embedded_at=now,
            tagging_duration_ms=tagging_duration_ms,
            caption_duration_ms=caption_duration_ms,
            embedding_duration_ms=embedding_duration_ms,
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

    except InsufficientBalanceError:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message="Insufficient credits")
        return {"status": "error", "message": "Insufficient credits"}
    except ZeroCostEstimateError as e:
        _update_job_status(db, job_id, JobStatus.FAILED, error_message=f"Billing config error: {e}")
        return {"status": "error", "message": f"Billing config error: {e}"}
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
        # Finalize billing: aggregate deferred usage records into one debit
        if job_id:
            try:
                filename_part = f" {image_filename}" if image_filename else ""
                finalize_job_billing(
                    db, user_id, job_id,
                    description=f"Describe{filename_part}",
                    create_debit=True,
                )
            except Exception:
                logger.warning(f"Failed to finalize billing for job {job_id}", exc_info=True)
        set_billing_deferred(False)
        set_billing_image(None)
        set_billing_job(None)
        set_trace_id(None)
        db.close()


@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def run_full_pipeline(self, job_id: int, user_id: int, trace_id: str | None = None, session_id: str | None = None) -> dict:
    """
    Run full pipeline: process all pending images, then cluster and summarize.
    """
    write_log(category=LogCategory.TASK, message="Task run_full_pipeline started",
              task_name="run_full_pipeline", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, trace_id=trace_id, session_id=session_id)
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
                dispatch(process_image_pipeline, image.id, user_id)
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
        set_trace_id(None)
        db.close()


@celery_app.task(bind=True, queue='clustering', acks_late=False, max_retries=0, reject_on_worker_lost=False)
def run_batch_reprocess(self, job_id: int, user_id: int, image_ids: list[int], trace_id: str | None = None, session_id: str | None = None) -> dict:
    """
    Reprocess a batch of images: reset each to INGESTED, dispatch process_image_pipeline,
    then poll until all images have finished processing.

    Idempotent: if tasks were already dispatched (e.g. after worker restart / re-delivery),
    Phase 1 is skipped and we go straight to polling.
    """
    write_log(category=LogCategory.TASK, message=f"Task run_batch_reprocess started ({len(image_ids)} images)",
              task_name="run_batch_reprocess", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, trace_id=trace_id, session_id=session_id)
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
                    dispatch(process_image_pipeline, image_id, user_id)
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
            job.completed_at = datetime.utcnow()
            job.result = {
                "total": len(image_ids),
                "queued": queued,
                "succeeded": succeeded,
                "failed": failed_count,
                "image_ids": image_ids,
                "dispatched": True,
            }
            if failed_count >= len(image_ids):
                job.status = JobStatus.FAILED
                job.error_message = f"All {failed_count} images failed"
            elif failed_count > 0:
                job.status = JobStatus.COMPLETED
                job.error_message = f"{failed_count}/{len(image_ids)} images failed"
            else:
                job.status = JobStatus.COMPLETED
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
        set_trace_id(None)
        db.close()


@celery_app.task(bind=True, queue='clustering', acks_late=False, max_retries=0, reject_on_worker_lost=False)
def run_batch_describe(
    self, job_id: int, user_id: int, image_ids: list[int],
    tag_prompt: str | None = None, description_prompt: str | None = None,
    provider: str | None = None, model: str | None = None,
    temperature: float | None = None, max_tokens_tag: int | None = None,
    max_tokens_describe: int | None = None,
    trace_id: str | None = None, session_id: str | None = None,
) -> dict:
    """
    Describe a batch of images: reset each to INGESTED, dispatch process_image_pipeline
    with custom prompts and provider/model, then poll until all images have finished.
    """
    write_log(category=LogCategory.TASK, message=f"Task run_batch_describe started ({len(image_ids)} images)",
              task_name="run_batch_describe", job_id=job_id, user_id=user_id)
    task_start = time.monotonic()
    _init_task_context(user_id, trace_id=trace_id, session_id=session_id)
    db = get_db()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()

        if job and job.status == JobStatus.CANCELLED:
            logger.info(f"Batch describe job {job_id} already cancelled, skipping")
            return {"status": "cancelled", "total": len(image_ids)}

        # Idempotency check
        already_dispatched = False
        if job and isinstance(job.result, dict) and job.result.get("dispatched"):
            already_dispatched = True
            logger.info(f"Batch describe job {job_id} already dispatched, skipping to Phase 2")

        if job and not already_dispatched:
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            job.total_items = len(image_ids)
            job.result = {"image_ids": image_ids}
            db.commit()

        image_service = get_image_service(db, user_id)
        queued = 0

        # Phase 1: Reset images and dispatch pipeline tasks
        if not already_dispatched:
            for image_id in image_ids:
                try:
                    image_service.update_status(image_id, ImageStatus.INGESTED)
                    dispatch(
                        process_image_pipeline,
                        image_id, user_id, tag_prompt, description_prompt,
                        provider=provider, model=model,
                        temperature=temperature, max_tokens_tag=max_tokens_tag,
                        max_tokens_describe=max_tokens_describe,
                    )
                    queued += 1
                except Exception as e:
                    logger.error(f"Failed to queue describe for image {image_id}: {e}")

            if job:
                job.result = {"image_ids": image_ids, "dispatched": True, "queued": queued}
                db.commit()

        # Phase 2: Poll until all images have finished
        image_id_set = set(image_ids)
        poll_interval = 5
        while True:
            db.expire_all()
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.status == JobStatus.CANCELLED:
                logger.info(f"Batch describe job {job_id} cancelled during polling")
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
            job.completed_at = datetime.utcnow()
            job.result = {
                "total": len(image_ids),
                "queued": queued,
                "succeeded": succeeded,
                "failed": failed_count,
                "image_ids": image_ids,
                "dispatched": True,
            }
            if failed_count >= len(image_ids):
                job.status = JobStatus.FAILED
                job.error_message = f"All {failed_count} images failed"
            elif failed_count > 0:
                job.status = JobStatus.COMPLETED
                job.error_message = f"{failed_count}/{len(image_ids)} images failed"
            else:
                job.status = JobStatus.COMPLETED
            db.commit()

        elapsed = (time.monotonic() - task_start) * 1000
        write_log(category=LogCategory.TASK,
                  message=f"Task run_batch_describe completed in {elapsed:.0f}ms ({succeeded} succeeded, {failed_count} failed)",
                  task_name="run_batch_describe", job_id=job_id, duration_ms=round(elapsed, 1), user_id=user_id)
        return {"status": "success", "total": len(image_ids), "succeeded": succeeded, "failed": failed_count}

    except Exception as e:
        elapsed = (time.monotonic() - task_start) * 1000
        logger.error(f"Batch describe failed: {e}")
        write_log(category=LogCategory.TASK, message=f"Task run_batch_describe failed: {e}",
                  level=LogLevel.ERROR, task_name="run_batch_describe", job_id=job_id,
                  duration_ms=round(elapsed, 1), extra={"error": _unwrap_error(e)}, user_id=user_id)
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            db.commit()
        raise
    finally:
        set_trace_id(None)
        db.close()


@celery_app.task(bind=True)
def delete_folder_with_images(self, folder_id: int, user_id: int, job_id: int, trace_id: str | None = None, session_id: str | None = None) -> dict:
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


@celery_app.task
def cleanup_stale_reservations():
    """Release reservations from stale PENDING decisions (older than 2 hours)."""
    from datetime import timedelta

    from app.models.cost_decision import CostDecision, DecisionStatus
    from app.services.billing_service import BillingService

    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=2)
        stale = (
            db.query(CostDecision)
            .filter(
                CostDecision.status == DecisionStatus.PENDING.value,
                CostDecision.created_at < cutoff,
                CostDecision.reserved_sparks > 0,
            )
            .all()
        )
        for decision in stale:
            released = decision.reserved_sparks
            svc = BillingService(db, decision.user_id)
            svc.release_reservation(released)
            decision.reserved_sparks = 0
            decision.status = DecisionStatus.FAILED.value
            decision.error_message = "stale reservation cleanup"
            decision.updated_at = datetime.utcnow()
            db.commit()
            logger.info(
                "STALE_CLEANUP | decision=%s user=%s released=%d sparks",
                decision.id, decision.user_id, released,
            )
        if stale:
            logger.info("Cleaned up %d stale reservations", len(stale))
    except Exception:
        logger.warning("Failed to clean up stale reservations", exc_info=True)
        db.rollback()
    finally:
        db.close()


@celery_app.task
def monitor_queue_health():
    """Periodic task to monitor queue depths, oldest pending job age, and completion rate."""
    import redis as redis_lib

    from app.core.config import get_settings as _get_settings

    _settings = _get_settings()
    db = SessionLocal()
    try:
        # Queue depths from Redis LLEN
        queue_depths = {}
        try:
            r = redis_lib.from_url(_settings.redis_url, socket_timeout=2, socket_connect_timeout=2)
            for queue_name in ("celery", "clustering", "generation"):
                queue_depths[queue_name] = r.llen(queue_name)
            r.close()
        except Exception as e:
            logger.warning(f"Failed to read queue depths from Redis: {e}")

        # Oldest pending job age
        oldest_pending_age_s = None
        try:
            oldest_pending = (
                db.query(Job)
                .filter(Job.status == JobStatus.PENDING)
                .order_by(Job.created_at.asc())
                .first()
            )
            if oldest_pending and oldest_pending.created_at:
                oldest_pending_age_s = (datetime.utcnow() - oldest_pending.created_at).total_seconds()
        except Exception as e:
            logger.warning(f"Failed to query oldest pending job: {e}")

        # Completion rate (last hour)
        completion_rate = None
        try:
            from sqlalchemy import func

            one_hour_ago = datetime.utcnow() - __import__("datetime").timedelta(hours=1)
            completed = (
                db.query(func.count(Job.id))
                .filter(Job.status == JobStatus.COMPLETED, Job.completed_at >= one_hour_ago)
                .scalar()
            ) or 0
            failed = (
                db.query(func.count(Job.id))
                .filter(Job.status == JobStatus.FAILED, Job.completed_at >= one_hour_ago)
                .scalar()
            ) or 0
            total = completed + failed
            completion_rate = round(completed / total, 3) if total > 0 else None
        except Exception as e:
            logger.warning(f"Failed to compute completion rate: {e}")

        logger.info(
            "Queue health check",
            extra={
                "event_type": "queue_health",
                "queue_depths": queue_depths,
                "oldest_pending_age_s": oldest_pending_age_s,
                "completion_rate": completion_rate,
                "completed_last_hour": completed if 'completed' in dir() else None,
                "failed_last_hour": failed if 'failed' in dir() else None,
            },
        )
    except Exception:
        logger.warning("monitor_queue_health failed", exc_info=True)
    finally:
        db.close()
