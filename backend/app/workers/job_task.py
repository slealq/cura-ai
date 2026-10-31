"""Worker leases independent of Celery Beat and task progress counters."""
import inspect
import logging
import threading
from datetime import datetime

from celery import Task
from celery.exceptions import Ignore

logger = logging.getLogger(__name__)


class JobTask(Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        from app.db.base import SessionLocal
        from app.models import Job, JobStatus
        from app.services.job_recovery import TERMINAL

        bound = inspect.signature(self.run).bind_partial(*args, **kwargs)
        job_id = bound.arguments.get('job_id')
        with SessionLocal() as db:
            query = db.query(Job)
            if job_id:
                query = query.filter(Job.id == job_id)
            elif self.request.id:
                query = query.filter(Job.celery_task_id == self.request.id)
            else:
                return super().__call__(*args, **kwargs)
            job = query.first()
            if job and job.status in TERMINAL:
                raise Ignore()
            if job:
                job_id = job.id
                job.updated_at = datetime.utcnow()
                if job.status == JobStatus.PENDING:
                    job.status = JobStatus.RUNNING
                    job.started_at = job.started_at or datetime.utcnow()
                db.commit()
        if not job_id:
            return super().__call__(*args, **kwargs)

        stop = threading.Event()

        def heartbeat():
            while not stop.wait(60):
                try:
                    with SessionLocal() as db:
                        db.query(Job).filter(
                            Job.id == job_id,
                            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                        ).update({Job.updated_at: datetime.utcnow()}, synchronize_session=False)
                        db.commit()
                except Exception:
                    logger.warning('Job %s heartbeat failed', job_id, exc_info=True)

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            return super().__call__(*args, **kwargs)
        finally:
            stop.set()
            thread.join(timeout=1)
