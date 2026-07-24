"""Hermetic tests for reconciliation of stuck generation jobs."""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, lazyload

from app.models.cost_decision import DecisionStatus
from app.models.generated_image import GenerationStatus
from app.models.job import Job, JobStatus, JobType
from app.services import billing_service as billing_service_module
from app.workers import tasks as tasks_module


def _query_returning(rows):
    query = Mock()
    query.filter.return_value = query
    query.all.return_value = rows
    return query


def _run_task(monkeypatch, jobs, generated_images=None, decisions=None):
    db = Mock()
    db.query.side_effect = [
        _query_returning(jobs),
        *(
            query
            for _job in jobs
            for query in (
                _query_returning(generated_images or []),
                _query_returning(decisions or []),
            )
        ),
    ]
    billing_service = Mock()
    billing_service_class = Mock(return_value=billing_service)
    monkeypatch.setattr(tasks_module, "SessionLocal", Mock(return_value=db))
    monkeypatch.setattr(
        billing_service_module, "BillingService", billing_service_class
    )

    tasks_module.fail_stuck_generation_jobs.run()

    return db, billing_service_class, billing_service


@pytest.fixture
def job_db():
    """Provide a fresh SQLite session containing only the jobs table."""
    engine = create_engine("sqlite:///:memory:")
    Job.metadata.create_all(engine, tables=[Job.__table__])
    session = Session(engine, expire_on_commit=False)
    yield session
    session.close()


def test_stuck_running_job_fails_images_and_releases_reservation(monkeypatch):
    job = Mock(
        id=101,
        user_id=7,
        job_type=JobType.GENERATE_IMAGE,
        status=JobStatus.RUNNING,
        updated_at=datetime.utcnow() - timedelta(minutes=31),
    )
    generated_image = Mock(status=GenerationStatus.GENERATING, error_message=None)
    decision = Mock(
        user_id=7,
        status=DecisionStatus.PENDING.value,
        reserved_sparks=Decimal("12.5"),
    )

    db, billing_service_class, billing_service = _run_task(
        monkeypatch, [job], [generated_image], [decision]
    )

    assert job.status == JobStatus.FAILED
    assert "no progress for 30+ minutes" in job.error_message
    assert job.completed_at is not None
    assert generated_image.status == GenerationStatus.FAILED
    assert generated_image.error_message == "Parent job failed: worker likely died mid-task"
    billing_service_class.assert_called_once_with(db, 7)
    billing_service.release_reservation.assert_called_once_with(Decimal("12.5"))
    assert decision.reserved_sparks == 0
    assert decision.status == DecisionStatus.FAILED.value
    assert decision.error_message == "stuck job cleanup"
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_stuck_pending_job_uses_distinct_dispatch_error(monkeypatch):
    job = Mock(
        id=102,
        user_id=8,
        job_type=JobType.EDIT_IMAGE,
        status=JobStatus.PENDING,
        celery_task_id=None,
        created_at=datetime.utcnow() - timedelta(minutes=31),
    )

    db, _, _ = _run_task(monkeypatch, [job])

    assert job.status == JobStatus.FAILED
    assert "without a Celery task ID" in job.error_message
    assert "no progress for 30+ minutes" not in job.error_message
    db.commit.assert_called_once()


def test_filter_selects_only_stuck_in_scope_generation_jobs(monkeypatch, job_db):
    now = datetime.utcnow()
    stale_running = Job(
        user_id=1,
        job_type=JobType.GENERATE_IMAGE,
        status=JobStatus.RUNNING,
        updated_at=now - timedelta(minutes=31),
    )
    active_running = Job(
        user_id=1,
        job_type=JobType.GENERATE_IMAGE,
        status=JobStatus.RUNNING,
        updated_at=now - timedelta(minutes=5),
    )
    stale_pending = Job(
        user_id=1,
        job_type=JobType.EDIT_IMAGE,
        status=JobStatus.PENDING,
        celery_task_id=None,
        created_at=now - timedelta(minutes=31),
    )
    recent_pending = Job(
        user_id=1,
        job_type=JobType.GENERATE_IMAGE,
        status=JobStatus.PENDING,
        celery_task_id=None,
        created_at=now - timedelta(minutes=5),
    )
    stale_training = Job(
        user_id=1,
        job_type=JobType.LORA_TRAIN,
        status=JobStatus.RUNNING,
        updated_at=now - timedelta(minutes=31),
    )
    job_db.add_all(
        [
            stale_running,
            active_running,
            stale_pending,
            recent_pending,
            stale_training,
        ]
    )
    job_db.commit()

    db = Mock()

    def query(model):
        if model is Job:
            return job_db.query(Job).options(lazyload(Job.image))
        return _query_returning([])

    db.query.side_effect = query
    db.commit.side_effect = job_db.commit
    db.rollback.side_effect = job_db.rollback
    billing_service_class = Mock()
    monkeypatch.setattr(tasks_module, "SessionLocal", Mock(return_value=db))
    monkeypatch.setattr(
        billing_service_module, "BillingService", billing_service_class
    )

    tasks_module.fail_stuck_generation_jobs.run()

    assert stale_running.status == JobStatus.FAILED
    assert stale_pending.status == JobStatus.FAILED
    assert active_running.status == JobStatus.RUNNING
    assert recent_pending.status == JobStatus.PENDING
    assert stale_training.status == JobStatus.RUNNING
    assert db.commit.call_count == 2
    billing_service_class.assert_not_called()


def test_job_without_pending_reservation_does_not_error(monkeypatch):
    job = Mock(
        id=104,
        user_id=9,
        job_type=JobType.BATCH_EDIT,
        status=JobStatus.RUNNING,
        updated_at=datetime.utcnow() - timedelta(minutes=31),
    )

    db, billing_service_class, _ = _run_task(monkeypatch, [job], decisions=[])

    assert job.status == JobStatus.FAILED
    billing_service_class.assert_not_called()
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
