"""Service for writing and querying pipeline debug logs."""
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.pipeline_log import LogCategory, LogLevel, PipelineLog

logger = logging.getLogger(__name__)


def write_log(
    category: LogCategory,
    message: str,
    level: LogLevel = LogLevel.INFO,
    image_id: int | None = None,
    job_id: int | None = None,
    task_name: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    operation: str | None = None,
    duration_ms: float | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    provider_cost: float | None = None,
    success: bool | None = None,
    extra: dict | None = None,
    user_id: int | None = None,
) -> None:
    """Write a log entry. Opens and closes its own session to stay independent."""
    db = SessionLocal()
    try:
        # For API call logs, inherit context from billing thread-local if not explicitly set
        effective_image_id = image_id
        effective_user_id = user_id
        if category == LogCategory.API_CALL:
            from app.services.billing_context import get_billing_image, get_billing_job, get_billing_user, get_trace_id
            if effective_image_id is None:
                effective_image_id = get_billing_image()
            if effective_user_id is None:
                effective_user_id = get_billing_user()
            if job_id is None:
                job_id = get_billing_job()
        else:
            from app.services.billing_context import get_trace_id

        entry = PipelineLog(
            user_id=effective_user_id,
            level=level,
            category=category,
            message=message,
            image_id=effective_image_id,
            job_id=job_id,
            task_name=task_name,
            provider=provider,
            model=model,
            operation=operation,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            success=success,
            extra=extra,
            trace_id=get_trace_id(),
        )
        db.add(entry)
        db.commit()

        # Record usage for successful API calls
        if category == LogCategory.API_CALL and success is True:
            from app.services.billing_context import get_billing_user, is_billing_deferred
            from app.services.billing_orchestrator import ORCHESTRATOR_ENABLED_OPS

            effective_user_id = user_id or get_billing_user()
            if effective_user_id and provider and operation:
                # If this operation is managed by the orchestrator, store
                # tokens in context for the orchestrator to pick up and
                # skip the legacy record_usage_standalone() path.
                if operation in ORCHESTRATOR_ENABLED_OPS:
                    from app.services.billing_context import set_last_api_call_tokens
                    set_last_api_call_tokens(input_tokens, output_tokens, provider_cost)
                    entry.billing_failed = False
                    db.commit()
                else:
                    try:
                        from app.services.billing_service import record_usage_standalone

                        record_usage_standalone(
                            user_id=effective_user_id,
                            provider=provider,
                            model=model or "unknown",
                            operation=operation,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            pipeline_log_id=entry.id,
                            provider_cost=provider_cost,
                            defer_debit=is_billing_deferred(),
                        )
                        entry.billing_failed = False
                        db.commit()
                    except Exception as usage_err:
                        logger.error(f"Failed to record usage: {usage_err}", exc_info=True)
                        entry.billing_failed = True
                        db.commit()
    except Exception as e:
        logger.warning(f"Failed to write pipeline log: {e}")
        db.rollback()
    finally:
        db.close()


def query_logs(
    db: Session,
    user_id: int,
    category: LogCategory | None = None,
    level: LogLevel | None = None,
    image_id: int | None = None,
    job_id: int | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[PipelineLog], int]:
    """Query logs with filtering. Returns (logs, total_count)."""
    query = db.query(PipelineLog).filter(PipelineLog.user_id == user_id)

    if category:
        query = query.filter(PipelineLog.category == category)
    if level:
        query = query.filter(PipelineLog.level == level)
    if image_id is not None:
        query = query.filter(PipelineLog.image_id == image_id)
    if job_id is not None:
        query = query.filter(PipelineLog.job_id == job_id)
    if search:
        query = query.filter(PipelineLog.message.ilike(f"%{search}%"))

    total = query.count()
    logs = (
        query.order_by(PipelineLog.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return logs, total


def cleanup_old_logs(days: int = 7) -> int:
    """Delete log entries older than `days`. Returns count deleted."""
    db = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        count = (
            db.query(PipelineLog)
            .filter(PipelineLog.created_at < cutoff)
            .delete()
        )
        db.commit()
        return count
    finally:
        db.close()
