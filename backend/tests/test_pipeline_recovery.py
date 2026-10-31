"""Database-backed, hermetic coverage of leases, cancellation and recovery."""
import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.jobs import _check_no_active_batch, cancel_job
from app.models import (
    Cluster,
    ClusterMembership,
    CostDecision,
    Folder,
    FolderImage,
    GeneratedImage,
    Image,
    ImageMetadata,
    Job,
    JobStatus,
    JobType,
    UserBalance,
)
from app.services import job_recovery
from app.services.pipeline_errors import MAX_ERROR_LENGTH, readable_error, safe_details
from scripts.repair_pipeline import repair


@compiles(TSVECTOR, 'sqlite')
@compiles(JSONB, 'sqlite')
def compile_jsonb(type_, compiler, **kw):
    return 'JSON'


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')

    @event.listens_for(engine, 'connect')
    def sqlite_functions(conn, record):
        conn.create_function('greatest', 2, max)

    Job.metadata.create_all(engine, tables=[model.__table__ for model in (
        Image, ImageMetadata, Job, CostDecision, GeneratedImage, UserBalance, Folder, FolderImage, Cluster, ClusterMembership,
    )])
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def make_job(db, **kw):
    defaults = dict(user_id=1, job_type=JobType.BATCH_DESCRIBE, status=JobStatus.RUNNING,
                    updated_at=datetime.utcnow() - timedelta(hours=1))
    job = Job(**(defaults | kw))
    db.add(job)
    db.commit()
    return job


def reserve(db, job):
    balance = UserBalance(user_id=1, balance=10, balance_sparks=10000, reserved_sparks=17)
    decision = CostDecision(user_id=1, job_id=job.id, operation='describe', provider='fal',
                            model='test', reserved_sparks=17, status='pending')
    db.add_all([balance, decision])
    db.commit()
    return balance, decision


def test_reaper_releases_once_and_keeps_live_jobs_and_other_users(db):
    stale = make_job(db)
    live = make_job(db, updated_at=datetime.utcnow())
    other = make_job(db, user_id=2)
    balance, decision = reserve(db, stale)
    assert job_recovery.reap_stale_jobs(db, 1) == 1
    db.refresh(balance)
    assert balance.reserved_sparks == 0
    assert balance.balance_sparks == 10000
    assert decision.status == 'failed'
    assert decision.reserved_sparks == 0
    assert stale.completed_at
    assert 'lease expired' in stale.error_message
    assert live.status == JobStatus.RUNNING
    assert other.status == JobStatus.RUNNING
    assert job_recovery.reap_stale_jobs(db, 1) == 0


def test_cancel_parent_releases_child_even_when_revoke_fails(db, monkeypatch):
    parent = make_job(db, celery_task_id='parent')
    child = make_job(db, job_type=JobType.REPROCESS, parameters={'parent_job_id': parent.id})
    balance, decision = reserve(db, child)
    from app.workers.celery_app import celery_app
    monkeypatch.setattr(celery_app.control, 'revoke', Mock(side_effect=ConnectionError))
    result = asyncio.run(cancel_job(parent.id, db, SimpleNamespace(id=1)))
    db.refresh(balance)
    assert result['status'] == 'cancelled'
    assert parent.status == child.status == JobStatus.CANCELLED
    assert parent.completed_at and child.completed_at
    assert decision.status == 'cancelled'
    assert balance.reserved_sparks == 0
    job_recovery.finish_job(db, parent, JobStatus.CANCELLED, 'Cancelled by user')
    db.commit()
    db.refresh(balance)
    assert balance.reserved_sparks == 0


def test_pending_dispatch_grace_and_zombie_batch_guard(db):
    stale = make_job(db, job_type=JobType.BATCH_REPROCESS)
    recent = make_job(db, status=JobStatus.PENDING, job_type=JobType.TAG,
                      created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    queued = make_job(db, status=JobStatus.PENDING, job_type=JobType.TAG, celery_task_id='queued',
                     created_at=datetime.utcnow() - timedelta(hours=2))
    _check_no_active_batch(db, 1)
    assert stale.status == JobStatus.FAILED
    assert recent.status == queued.status == JobStatus.PENDING


def test_error_redacts_payload_and_retains_provider_reason():
    error = ValueError("image too large: {'input': 'data:image/png;base64," + 'AbC0' * 20000 + "', 'type': 'too_large'}")
    result = readable_error(error)
    assert 'image too large' in result and 'too_large' in result
    assert 'base64' not in result and 'AbC0' not in result
    assert len(readable_error('short words ' * 1000)) <= MAX_ERROR_LENGTH
    assert readable_error(ValueError()) == 'ValueError'
    assert readable_error(None)
    assert safe_details({'error': [str(error)]}) == {'error': [result]}
    assert Job(error_message=str(error)).error_message == result


def test_repair_dry_run_and_repeat_are_safe(db):
    zombie = make_job(db)
    balance, decision = reserve(db, zombie)
    balance.reserved_sparks += Decimal('100')  # historical untracked hold
    folder = Folder(user_id=1, name='Jazz')
    image = Image(user_id=1, object_key='test.jpg', file_hash='a' * 64,
                  source='upload', status='failed', error_message='Grok 4 Fast is deprecated.')
    db.add_all([folder, image])
    db.flush()
    db.add(FolderImage(folder_id=folder.id, image_id=image.id))
    db.commit()
    assert repair(db, 1, 'Jazz', True) == 1
    db.refresh(balance)
    assert balance.reserved_sparks == 117
    assert zombie.status == JobStatus.RUNNING
    assert repair(db, 1, 'Jazz', False) == 1
    db.refresh(balance)
    assert balance.reserved_sparks == 0
    assert image.status.value == 'ingested'
    assert image.error_message is None
    assert repair(db, 1, 'Jazz', False) == 0


def test_lowercase_clusters_remain_available_in_list_and_detail(db):
    from app.models import ClusteringMethod
    from app.services.cluster_service import ClusterService

    cluster = Cluster(user_id=1, method=ClusteringMethod.HDBSCAN, run_id='legacy', size=0)
    db.add(cluster)
    db.commit()
    db.execute(text("update clusters set method='hdbscan' where id=:id"), {'id': cluster.id})
    db.commit()
    db.expire_all()
    service = ClusterService.__new__(ClusterService)
    service.db, service.user_id = db, 1
    assert service.get_clusters()[0].method == ClusteringMethod.HDBSCAN
    assert service.get_cluster(cluster.id).method == ClusteringMethod.HDBSCAN
    assert service.get_latest_clusters()[0].id == cluster.id


def test_failed_images_are_available_to_not_described_filter(db):
    from app.models import ImageStatus
    from app.services.image_service import ImageService

    image = Image(user_id=1, object_key='failed.jpg', file_hash='b'*64,
                  source='upload', status=ImageStatus.FAILED, error_message='provider error')
    db.add(image)
    db.commit()
    service = ImageService.__new__(ImageService)
    service.db, service.user_id = db, 1
    assert service.get_images(max_status=ImageStatus.TAGGED)[0].id == image.id
    assert service.count_images(max_status=ImageStatus.TAGGED) == 1
    from app.schemas import ImageResponse
    assert ImageResponse.model_validate(image).error_message == 'provider error'


def test_cancelled_task_is_not_executed_after_redelivery(db, monkeypatch):
    from celery.exceptions import Ignore

    from app.db import base
    from app.workers.job_task import JobTask

    job = make_job(db, status=JobStatus.CANCELLED)

    class CancelledTask(JobTask):
        name = 'test.cancelled'

        def run(self, job_id):
            pytest.fail('A cancelled task must never invoke a provider')

    monkeypatch.setattr(base, 'SessionLocal', lambda: db)
    task = CancelledTask()
    with pytest.raises(Ignore):
        task(job.id)


def test_registered_pipeline_tasks_use_worker_leases():
    from app.workers.job_task import JobTask
    from app.workers.tasks import process_image_pipeline, run_batch_describe

    assert isinstance(process_image_pipeline, JobTask)
    assert isinstance(run_batch_describe, JobTask)


def test_pipeline_failure_before_estimation_is_readable_and_terminal(db, monkeypatch):
    from unittest.mock import AsyncMock

    from app.services import image_service as images
    from app.workers import tasks

    image = Image(user_id=1, object_key='provider.jpg', file_hash='c'*64,
                  source='upload', status='ingested')
    db.add(image)
    db.commit()
    job = make_job(db, job_type=JobType.REPROCESS, image_id=image.id)
    service = images.ImageService.__new__(images.ImageService)
    service.db, service.user_id = db, 1
    service.get_image_data = AsyncMock(return_value=b'image')
    monkeypatch.setattr(tasks, 'get_db', lambda: db)
    monkeypatch.setattr(tasks, 'get_image_service', lambda *a: service)
    monkeypatch.setattr(tasks, 'get_settings_service', lambda *a: Mock())
    monkeypatch.setattr(tasks, 'get_tagger', Mock(side_effect=ValueError()))
    monkeypatch.setattr(tasks, 'write_log', Mock())
    monkeypatch.setattr(tasks, 'finalize_job_billing', Mock())
    with pytest.raises(ValueError):
        tasks.process_image_pipeline.run(image.id, 1, job_id=job.id)
    # The task closes its session; reload rather than relying on its identity map.
    assert db.get(Job, job.id).status == JobStatus.FAILED
    assert db.get(Image, image.id).error_message == 'ValueError'
