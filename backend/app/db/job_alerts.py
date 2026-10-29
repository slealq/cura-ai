"""Collect job failures per transaction and deliver only after the outer commit."""
from sqlalchemy import event, inspect

from app.core.config import get_settings

_KEY = "job_failure_alerts"


def register_job_alerts(session_factory):
    """Install listeners without importing models during database initialization."""
    @event.listens_for(session_factory, "before_flush")
    def collect(session, flush_context, instances):
        from app.models.job import Job

        tx = session.get_nested_transaction() or session.get_transaction()
        changes = session.info.setdefault(_KEY, {}).setdefault(tx, {})
        for job in session.new.union(session.dirty):
            if not isinstance(job, Job):
                continue
            history = inspect(job).attrs.status.history
            if job in session.new:
                initial = None
            elif history.has_changes():
                initial = history.deleted[0] if history.deleted else None
            else:
                continue
            if job not in changes:
                changes[job] = initial

    @event.listens_for(session_factory, "before_commit")
    def restore_expired(session):
        # A savepoint rollback expires affected objects, even those already tracked
        # by the outer transaction. Refresh while SQL is still permitted.
        if session.get_nested_transaction() is None:
            for job in session.info.get(_KEY, {}).get(session.get_transaction(), {}):
                try:
                    if inspect(job).expired and not inspect(job).deleted:
                        session.refresh(job, ["id", "status", "job_type", "error_message"])
                except Exception:
                    pass

    @event.listens_for(session_factory, "after_commit")
    def committed(session):
        from app.models.job import JobStatus
        from app.services.discord_alerts import send_failure_alert

        tx = session.get_nested_transaction() or session.get_transaction()
        groups = session.info.get(_KEY, {})
        changes = groups.pop(tx, {})
        if tx.nested:
            parent = tx.parent
            target = groups.setdefault(parent, {})
            for job, initial in changes.items():
                target.setdefault(job, initial)
            return
        session.info.pop(_KEY, None)
        for job, initial in changes.items():
            try:
                if initial != JobStatus.FAILED and job.status == JobStatus.FAILED and not inspect(job).deleted:
                    send_failure_alert(job.id, job.job_type, job.error_message, get_settings())
            except Exception:
                # Alerting must never interfere with committed bookkeeping.
                pass

    @event.listens_for(session_factory, "after_soft_rollback")
    def rolled_back(session, previous_transaction):
        groups = session.info.get(_KEY, {})
        groups.pop(previous_transaction, None)
        if previous_transaction.parent is None:
            session.info.pop(_KEY, None)
