"""My models mutations preserve artifacts and remain scoped to the current user."""
import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api import generation as api
from app.models.lora_model import LoraModelStatus
from app.services.generation_service import GenerationService


@pytest.fixture
def model_service(monkeypatch):
    service = Mock()
    monkeypatch.setattr(api, "get_generation_service", lambda db, user_id: service if user_id == 7 else None)
    monkeypatch.setattr(api, "_lora_to_response", lambda model, db: model)
    return service


def update(service, **values):
    db = Mock()
    result = asyncio.run(api.update_lora_model(
        12, api.UpdateLoraRequest(**values), db=db, current_user=SimpleNamespace(id=7),
    ))
    return result, db


def test_rename_preserves_training_and_weights(model_service):
    model = SimpleNamespace(name="Old", status=LoraModelStatus.TRAINING, weights_object_key="weights", job_id=9)
    model_service.get_lora_model.return_value = model
    result, db = update(model_service, name="  New name  ")
    assert result.name == "New name"
    assert result.status == LoraModelStatus.TRAINING
    assert result.weights_object_key == "weights"
    assert result.job_id == 9
    model_service.get_lora_model.assert_called_once_with(12)
    db.commit.assert_called_once()


@pytest.mark.parametrize("status", [LoraModelStatus.COMPLETED, LoraModelStatus.UPLOADED, LoraModelStatus.ARCHIVED])
def test_retire_preserves_model_artifacts(model_service, status):
    model = SimpleNamespace(name="Model", status=status, weights_object_key="weights", lora_url="url")
    model_service.get_lora_model.return_value = model
    result, db = update(model_service, retire=True)
    assert result.status == LoraModelStatus.ARCHIVED
    assert result.weights_object_key == "weights"
    assert result.lora_url == "url"
    model_service.delete_lora_model.assert_not_called()
    db.commit.assert_called_once()


@pytest.mark.parametrize("status", [LoraModelStatus.PENDING, LoraModelStatus.TRAINING, LoraModelStatus.FAILED])
def test_cannot_retire_unfinished_training(model_service, status):
    model_service.get_lora_model.return_value = SimpleNamespace(status=status)
    with pytest.raises(HTTPException) as exc:
        update(model_service, retire=True)
    assert exc.value.status_code == 400


def test_missing_or_other_users_model_is_not_found(model_service):
    model_service.get_lora_model.return_value = None
    with pytest.raises(HTTPException) as exc:
        update(model_service, name="Name")
    assert exc.value.status_code == 404


@pytest.mark.parametrize("name", ["", "   ", "x" * 257])
def test_rename_rejects_invalid_names(name):
    with pytest.raises(ValidationError):
        api.UpdateLoraRequest(name=name)


def test_made_with_includes_secondary_loras_and_scopes_count_and_list():
    from unittest.mock import patch

    from sqlalchemy.orm import Session

    service = GenerationService.__new__(GenerationService)
    service.user_id = 7
    service.db = Session()
    statements = []

    def capture(query):
        compiled = query.statement.compile(dialect=postgresql.dialect())
        statements.append(compiled)
        return []

    with patch("sqlalchemy.orm.Query.all", autospec=True, side_effect=capture), patch(
        "sqlalchemy.orm.Query.count", autospec=True, side_effect=lambda query: len(capture(query)),
    ):
        service.get_generated_images(lora_model_id=12)
        service.count_generated_images(lora_model_id=12)
    assert len(statements) == 2
    for statement in statements:
        sql = str(statement)
        assert "generated_images.user_id =" in sql
        assert "generated_images.lora_model_id =" in sql
        assert "CAST(" in sql and "JSONB) @>" in sql
        assert 7 in statement.params.values()
        assert 12 in statement.params.values()
        assert [{"lora_model_id": 12}] in statement.params.values()


@pytest.mark.parametrize("source", ["folder", "cluster"])
def test_training_rejects_another_users_source_before_creating_job(source):
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = None
    request = api.TrainLoraRequest(name="Selection", **{f"{source}_id": 13})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api.train_lora(request, db=db, current_user=SimpleNamespace(id=7)))
    assert exc.value.status_code == 404
    filters = db.query.return_value.filter.call_args.args
    assert any("user_id" in str(expression) for expression in filters)
    db.add.assert_not_called()
    db.commit.assert_not_called()
