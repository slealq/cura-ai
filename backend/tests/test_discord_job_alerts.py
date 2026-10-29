"""Transaction and privacy coverage for failed job alerts."""
import json
import logging
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import lazyload, sessionmaker

from app.core.config import Settings
from app.db.job_alerts import register_job_alerts
from app.models.job import Job, JobStatus, JobType
from app.services import discord_alerts


@pytest.fixture
def setup(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Job.metadata.create_all(engine, tables=[Job.__table__])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    register_job_alerts(factory)
    settings = Settings(environment="dev", discord_alert_webhook_url="https://example.invalid/dummy")
    monkeypatch.setattr("app.db.job_alerts.get_settings", lambda: settings)
    post = Mock(return_value=httpx.Response(204))
    monkeypatch.setattr(discord_alerts.httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(post))
    with factory() as session:
        yield session, settings, post
    engine.dispose()


def job(kind=JobType.TAG, status=JobStatus.PENDING):
    return Job(user_id=1, job_type=kind, status=status)


@pytest.mark.parametrize("kind", list(JobType))
def test_all_types_and_new_failed(setup, kind):
    session, _, post = setup
    item = job(kind, JobStatus.FAILED)
    session.add(item)
    session.commit()
    assert post.call_count == 1
    assert f"Type: {kind.value}" in json.loads(post.call_args.args[0].content)["content"]


def test_assignment_flush_repeat_and_rollback(setup):
    session, _, post = setup
    a, b = job(), job()
    session.add_all([a, b])
    session.commit()
    a.status = JobStatus.FAILED
    session.flush()
    a.error_message = "failure"
    b.status = JobStatus.FAILED
    session.flush()
    assert post.call_count == 0
    session.commit()
    assert post.call_count == 2
    a.error_message = "updated"
    a.status = JobStatus.FAILED
    session.commit()
    b.status = JobStatus.RUNNING
    session.flush()
    b.status = JobStatus.FAILED
    session.rollback()
    assert post.call_count == 2


def test_savepoint_rollback_and_commit(setup):
    session, _, post = setup
    a, b = job(), job()
    session.add_all([a, b])
    session.commit()
    a.status = JobStatus.FAILED
    session.flush()
    nested = session.begin_nested()
    b.status = JobStatus.FAILED
    session.flush()
    nested.rollback()
    session.commit()
    assert post.call_count == 1
    assert f"Job {a.id} failed" in json.loads(post.call_args.args[0].content)["content"]
    b = session.query(Job).options(lazyload(Job.image)).filter_by(id=2).one()
    with session.begin_nested():
        b.status = JobStatus.FAILED
        session.flush()
    assert post.call_count == 1
    session.commit()
    assert post.call_count == 2


def test_failed_commit(setup):
    session, _, post = setup
    session.add(job(status=JobStatus.FAILED))
    session.add(Job(user_id=None, job_type=JobType.TAG, status=JobStatus.PENDING))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert post.call_count == 0


@pytest.mark.parametrize("environment,url,expected", [("local", "https://example.invalid/dummy", 0), ("dev", "", 0), ("dev", "https://example.invalid/dummy", 1), ("prod", "https://example.invalid/dummy", 1)])
def test_gate(setup, environment, url, expected):
    from pydantic import SecretStr

    session, settings, post = setup
    settings.environment = environment
    settings.discord_alert_webhook_url = SecretStr(url)
    session.add(job(status=JobStatus.FAILED))
    session.commit()
    assert post.call_count == expected
    assert url not in repr(settings) if url else True


@pytest.mark.parametrize("error", [httpx.TimeoutException("secret url"), httpx.HTTPError("secret url")])
def test_http_errors_do_not_break_commit(setup, error, caplog):
    session, _, post = setup
    post.side_effect = error
    item = job(status=JobStatus.FAILED)
    session.add(item)
    session.commit()
    assert session.get(Job, item.id).status == JobStatus.FAILED
    assert "secret url" not in caplog.text


def test_payload_does_not_contain_sensitive_error_details(setup):
    session, _, post = setup
    item = job(status=JobStatus.FAILED)
    item.error_message = "Bearer abc password=secret sk-abc user@example.com /tmp/private https://user:pass@example.com/token @everyone prompt content"
    session.add(item)
    session.commit()
    payload = json.loads(post.call_args.args[0].content)
    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["content"] == f"Job {item.id} failed\nType: tag\nEnvironment: dev\nError: Job failed; details withheld"
    assert post.call_args.args[0].extensions["timeout"]["read"] == 2.0


def test_real_httpx_transport_has_no_url_in_info_logs(monkeypatch, caplog):
    from app.services.discord_alerts import send_failure_alert

    url = "https://example.invalid/api/webhooks/123/dummy-secret-token"
    settings = Settings(environment="dev", discord_alert_webhook_url=url)
    handler = Mock(return_value=httpx.Response(204))
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(handler))
    with caplog.at_level(logging.INFO):
        send_failure_alert(1, JobType.TAG, "failure", settings)
    assert handler.call_count == 1
    assert url not in caplog.text
    assert "dummy-secret-token" not in caplog.text


def test_response_error_does_not_break_commit(setup, caplog):
    session, _, post = setup
    post.return_value = httpx.Response(500)
    item = job(status=JobStatus.FAILED)
    session.add(item)
    session.commit()
    assert session.get(Job, item.id).status == JobStatus.FAILED
    assert "dummy" not in caplog.text


def test_expunge_and_delete(setup):
    session, _, post = setup
    a, b = job(), job()
    session.add_all([a, b])
    session.commit()
    a.status = JobStatus.FAILED
    b.status = JobStatus.FAILED
    session.flush()
    session.expunge(a)
    session.delete(b)
    session.commit()
    assert post.call_count == 1


def test_default_expiration_savepoint_and_refailure(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Job.metadata.create_all(engine, tables=[Job.__table__])
    factory = sessionmaker(bind=engine)  # Same expire_on_commit default as SessionLocal.
    register_job_alerts(factory)
    settings = Settings(environment="dev", discord_alert_webhook_url="https://example.invalid/dummy")
    monkeypatch.setattr("app.db.job_alerts.get_settings", lambda: settings)
    post = Mock(return_value=httpx.Response(204))
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(post))
    with factory() as session:
        item = job()
        session.add(item)
        session.commit()
        # Load with the relationship disabled because this fixture only creates jobs.
        item = session.query(Job).options(lazyload(Job.image)).one()
        item.status = JobStatus.FAILED
        session.flush()
        nested = session.begin_nested()
        item.status = JobStatus.RUNNING
        session.flush()
        nested.rollback()
        session.commit()
        assert post.call_count == 1
        item = session.query(Job).options(lazyload(Job.image)).one()
        item.status = JobStatus.RUNNING
        session.commit()
        item = session.query(Job).options(lazyload(Job.image)).one()
        item.status = JobStatus.FAILED
        session.commit()
        assert post.call_count == 2
    engine.dispose()
