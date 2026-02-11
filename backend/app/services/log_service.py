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
    success: bool | None = None,
    extra: dict | None = None,
) -> None:
    """Write a log entry. Opens and closes its own session to stay independent."""
    db = SessionLocal()
    try:
        entry = PipelineLog(
            level=level,
            category=category,
            message=message,
            image_id=image_id,
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
        )
        db.add(entry)
        db.commit()
    except Exception as e:
        logger.warning(f"Failed to write pipeline log: {e}")
        db.rollback()
    finally:
        db.close()


def query_logs(
    db: Session,
    category: LogCategory | None = None,
    level: LogLevel | None = None,
    image_id: int | None = None,
    job_id: int | None = None,
    search: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[PipelineLog], int]:
    """Query logs with filtering. Returns (logs, total_count)."""
    query = db.query(PipelineLog)

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
