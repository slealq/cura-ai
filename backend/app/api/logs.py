"""Debug logs API endpoints."""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models.pipeline_log import LogCategory, LogLevel, PipelineLog
from app.services.log_service import cleanup_old_logs, query_logs

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/logs", tags=["logs"])


class LogEntryResponse(BaseModel):
    id: int
    level: str
    category: str
    image_id: int | None
    job_id: int | None
    task_name: str | None
    message: str
    provider: str | None
    model: str | None
    operation: str | None
    duration_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    success: bool | None
    extra: dict | None
    created_at: str

    class Config:
        from_attributes = True


class LogListResponse(BaseModel):
    items: list[LogEntryResponse]
    total: int
    skip: int
    limit: int


class LogStatsResponse(BaseModel):
    total_logs: int
    api_calls: int
    errors: int
    total_tokens: int
    avg_duration_ms: float | None


@router.get("", response_model=LogListResponse)
async def list_logs(
    category: LogCategory | None = None,
    level: LogLevel | None = None,
    image_id: int | None = None,
    job_id: int | None = None,
    search: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Query pipeline logs with filtering."""
    logs, total = query_logs(
        db,
        category=category,
        level=level,
        image_id=image_id,
        job_id=job_id,
        search=search,
        skip=skip,
        limit=limit,
    )

    items = []
    for log in logs:
        items.append(
            LogEntryResponse(
                id=log.id,
                level=log.level.value if log.level else "info",
                category=log.category.value if log.category else "system",
                image_id=log.image_id,
                job_id=log.job_id,
                task_name=log.task_name,
                message=log.message,
                provider=log.provider,
                model=log.model,
                operation=log.operation,
                duration_ms=log.duration_ms,
                input_tokens=log.input_tokens,
                output_tokens=log.output_tokens,
                success=log.success,
                extra=log.extra,
                created_at=log.created_at.isoformat() if log.created_at else "",
            )
        )

    return LogListResponse(items=items, total=total, skip=skip, limit=limit)


@router.get("/stats", response_model=LogStatsResponse)
async def get_log_stats(db: Session = Depends(get_db)):
    """Get summary statistics for logs."""
    total = db.query(func.count(PipelineLog.id)).scalar() or 0
    api_calls = (
        db.query(func.count(PipelineLog.id))
        .filter(PipelineLog.category == LogCategory.API_CALL)
        .scalar()
        or 0
    )
    errors = (
        db.query(func.count(PipelineLog.id))
        .filter(PipelineLog.level == LogLevel.ERROR)
        .scalar()
        or 0
    )

    token_sum = (
        db.query(
            func.coalesce(func.sum(PipelineLog.input_tokens), 0)
            + func.coalesce(func.sum(PipelineLog.output_tokens), 0)
        )
        .filter(PipelineLog.category == LogCategory.API_CALL)
        .scalar()
        or 0
    )

    avg_duration = (
        db.query(func.avg(PipelineLog.duration_ms))
        .filter(
            PipelineLog.category == LogCategory.API_CALL,
            PipelineLog.duration_ms.isnot(None),
        )
        .scalar()
    )

    return LogStatsResponse(
        total_logs=total,
        api_calls=api_calls,
        errors=errors,
        total_tokens=token_sum,
        avg_duration_ms=round(avg_duration, 1) if avg_duration else None,
    )


@router.delete("/cleanup")
async def cleanup_logs(
    days: int = Query(7, ge=1, le=90),
):
    """Delete logs older than specified days."""
    count = cleanup_old_logs(days=days)
    return {"deleted": count, "older_than_days": days}
