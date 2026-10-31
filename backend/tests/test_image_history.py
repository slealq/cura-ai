"""Hermetic history lifecycle, worker inputs, ownership and storage contracts.

Postgres FK cascades are deliberately not simulated here.
"""
import asyncio
import io
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from app.api import images as routes
from app.core.security import get_current_user, get_current_user_from_token_param
from app.db.base import get_db
from app.models import GeneratedImage, Image
from app.services.image_history import attach_history, input_snapshot, read_history, remove_unused_copies, snapshot
from app.workers import generation_tasks


def run(coro):
    return asyncio.run(coro)


def db_mock(first=None):
    db = MagicMock()
    query = db.query.return_value
    query.filter.return_value = query
    query.filter_by.return_value = query
    query.join.return_value = query
    query.with_entities.return_value = query
    query.first.return_value = first
    query.all.return_value = []
    query.scalar.return_value = 0
    return db


def gen():
    return GeneratedImage(id=2, user_id=7, prompt='Exact prompt\nImage 1', negative_prompt='blur',
                          base_model='flux-dev', generation_provider='fal', created_at=datetime(2026, 10, 31),
                          generation_params={'loras': [{'lora_model_id': 4, 'lora_scale': 0.7}], 'steps': 28})


def test_library_snapshot_survives_generation_input_and_lora_removal():
    lora = SimpleNamespace(name='Dapple', base_model='flux-dev', trigger_word='dapple')
    db = db_mock(lora)
    generation = gen()
    history = snapshot(db, generation, [{'label': 'Image 1', 'filename': 'dog.jpg', 'source_key': 'dog.jpg', 'copy_key': '7-hash.jpg'}])
    image = Image(id=8, user_id=7, object_key='result.jpg', history=None)
    # Source no longer resolves; independent JSON still attaches and stores its stable link.
    db.query.return_value.first.return_value = None
    attach_history(db, image, history)
    generation.history = None
    history['prompt'] = 'changed elsewhere'
    view = read_history(db, image)
    assert view['prompt'] == 'Exact prompt\nImage 1'
    assert view['negative_prompt'] == 'blur'
    assert view['inputs'][0]['copy_key'] == '7-hash.jpg'
    assert view['inputs'][0]['image_id'] is None
    assert view['loras'][0] == {'id': 4, 'name': 'Dapple', 'strength': 0.7, 'base_model': 'flux-dev', 'trigger_word': 'dapple', 'deleted': True}
    assert view['model'] == {'key': 'flux-dev', 'name': 'flux-dev', 'offered': False}


def test_retired_model_keeps_runtime_catalog_display_name(monkeypatch):
    from app.services import image_history
    monkeypatch.setattr(image_history, 'get_image_model', lambda key, kind: SimpleNamespace(label='Old FLUX display name', supports_output_format=True, kind='generate', endpoint='old', params={}, fixed_payload={}))
    generation = gen()
    generation.generation_params = {}
    history = snapshot(db_mock(), generation)
    monkeypatch.setattr(image_history, 'get_image_model', lambda key, kind: None)
    image = Image(id=8, user_id=7, history=history)
    assert read_history(db_mock(), image)['model'] == {'key': 'flux-dev', 'name': 'Old FLUX display name', 'offered': False}


def test_failed_copy_is_best_effort_and_keeps_input_metadata():
    output = io.BytesIO()
    PILImage.new('RGB', (1600, 900)).save(output, 'PNG')
    storage = SimpleNamespace(save_history_copy=AsyncMock(side_effect=OSError('storage unavailable')))
    item = run(input_snapshot(storage, 7, output.getvalue(), 'dog.png', 'dog.png'))
    assert item['copy_key'] is None
    assert item['width'] == 1600
    assert item['height'] == 900
    assert len(item['file_hash']) == 64


def test_copies_are_800px_content_addressed_and_per_user():
    output = io.BytesIO()
    PILImage.new('RGB', (1600, 900)).save(output, 'PNG')
    storage = SimpleNamespace(save_history_copy=AsyncMock())
    first = run(input_snapshot(storage, 7, output.getvalue(), 'a.png'))
    second = run(input_snapshot(storage, 7, output.getvalue(), 'b.png'))
    other = run(input_snapshot(storage, 8, output.getvalue(), 'a.png'))
    assert first['copy_key'] == second['copy_key'] != other['copy_key']
    copied = storage.save_history_copy.await_args_list[0].args[0]
    assert PILImage.open(io.BytesIO(copied)).size == (800, 450)


def test_edit_history_order_is_provider_order_including_uploads(monkeypatch):
    image = SimpleNamespace(original_filename='gallery.jpg', object_key='gallery', mime_type='image/jpeg')
    image_service = SimpleNamespace(get_image=lambda id: image, get_image_data=AsyncMock(return_value=b'gallery'))
    generation = SimpleNamespace(object_key='generated', mime_type='image/png')
    gen_service = SimpleNamespace(get_generated_image=lambda id: generation, get_generated_image_data=AsyncMock(return_value=b'generated'))
    monkeypatch.setattr(generation_tasks, 'get_image_service', lambda *args: image_service)
    monkeypatch.setattr(generation_tasks, 'get_generation_service', lambda *args: gen_service)
    from app.services import storage as storage_module
    monkeypatch.setattr(storage_module, 'get_storage_service', lambda: SimpleNamespace(get_generated_image=AsyncMock(return_value=b'uploaded')))
    inputs = []
    uris = generation_tasks._resolve_edit_sources(db_mock(), {'sources': {'upload_keys': ['upload.png'], 'generated_ids': [2], 'image_ids': [1]}}, 7, inputs)
    import base64
    assert [base64.b64decode(uri.split(',')[1]) for uri in uris] == [b'gallery', b'generated', b'uploaded']
    assert [item['label'] for item in inputs] == ['Image 1', 'Image 2', 'Image 3']
    # Invalid input bytes make every copy fail, but source resolution still succeeds.
    assert all(item['copy_key'] is None for item in inputs)


def test_shared_copy_only_removed_after_last_history():
    storage = SimpleNamespace(delete_file=AsyncMock())
    db = db_mock()
    db.query.return_value.filter.return_value.__iter__.side_effect = lambda: iter([({'inputs': [{'copy_key': '7-shared.jpg'}]},)])
    run(remove_unused_copies(db, storage, ['7-shared.jpg', '7-unused.jpg']))
    storage.delete_file.assert_awaited_once_with('history', '7-unused.jpg')


@pytest.mark.parametrize('path', ['/api/images/99/history', '/api/images/99/history/inputs/0'])
def test_history_routes_hide_foreign_images_and_require_auth(path):
    app = FastAPI()
    app.include_router(routes.router, prefix='/api')
    db = db_mock()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.get(path).status_code in (401, 403)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        app.dependency_overrides[get_current_user_from_token_param] = lambda: SimpleNamespace(id=7)
        assert client.get(path).status_code == 404
    args = db.query.return_value.filter.call_args.args
    assert 'images.id' in str(args[0])
    assert args[0].right.value == 99
    assert 'images.user_id' in str(args[1])
    assert args[1].right.value == 7


def test_used_by_filters_owned_sources_and_owned_links():
    from app.services.image_history import used_by
    db = db_mock()
    assert used_by(db, 7, [99]) == 0
    clauses = [str(arg) for call in db.query.return_value.filter.call_args_list for arg in call.args]
    assert any('images.user_id' in clause for clause in clauses)
    assert any('image_history_links.user_id' in clause for clause in clauses)


def test_duplicate_library_file_receives_history(monkeypatch):
    from app.services import image_service
    from app.services.generation_service import GenerationService
    db = db_mock()
    image = Image(id=8, user_id=7, object_key='existing.png', history=None)
    db.query.return_value.first.side_effect = [None, image]
    service = GenerationService.__new__(GenerationService)
    service.db, service.user_id = db, 7
    service.storage = SimpleNamespace(compute_file_hash=lambda data: 'hash')
    monkeypatch.setattr(image_service, 'get_image_service', lambda *args: SimpleNamespace(fast_ingest=AsyncMock(return_value=None)))
    generation = gen()
    generation.history = {'prompt': 'exact', 'inputs': []}
    assert run(service.add_to_library(generation, b'result')) is None
    assert image.history == generation.history
    assert image.history is not generation.history
    db.commit.assert_called_once()


def test_edit_job_finishes_when_history_copy_fails(monkeypatch):
    from app.services import storage as storage_module
    from app.services.model_catalog import DEFAULT_EDIT_MODEL
    db = db_mock()
    generation = gen()
    generation.generation_params = {'mode': 'edit', 'edit_model': DEFAULT_EDIT_MODEL, 'sources': {'image_ids': [1]}}
    service = SimpleNamespace(get_generated_image=lambda id: generation, save_generated_result=AsyncMock())
    output = io.BytesIO()
    PILImage.new('RGB', (20, 20)).save(output, 'PNG')
    monkeypatch.setattr(generation_tasks, '_get_db', lambda: db)
    monkeypatch.setattr(generation_tasks, '_init_task_context', lambda *args, **kwargs: None)
    monkeypatch.setattr(generation_tasks, 'write_log', lambda **kwargs: None)
    monkeypatch.setattr(generation_tasks, 'finalize_job_billing', lambda *args: None)
    statuses = MagicMock()
    monkeypatch.setattr(generation_tasks, '_update_job_status', statuses)
    monkeypatch.setattr(generation_tasks, 'get_generation_service', lambda *args: service)
    monkeypatch.setattr(generation_tasks, 'get_image_service', lambda *args: SimpleNamespace(
        get_image=lambda id: SimpleNamespace(original_filename='source.png', object_key='source', mime_type='image/png'),
        get_image_data=AsyncMock(return_value=output.getvalue())))
    monkeypatch.setattr(storage_module, 'get_storage_service', lambda: SimpleNamespace(save_history_copy=AsyncMock(side_effect=OSError('offline'))))
    editor = SimpleNamespace(edit=AsyncMock(return_value=SimpleNamespace(images=[b'result'], widths=[20], heights=[20], seed=4, metadata={})))
    monkeypatch.setattr(generation_tasks, 'get_editor', lambda **kwargs: editor)
    context = MagicMock()
    context.__enter__.return_value = SimpleNamespace(skipped=False, call=lambda fn, coro: fn(coro))
    monkeypatch.setattr(generation_tasks, 'billable', lambda *args, **kwargs: context)
    response = generation_tasks.edit_image.run(generation.id, job_id=10, user_id=7)
    assert response['status'] == 'success'
    service.save_generated_result.assert_awaited_once()
    assert generation.history['inputs'][0]['copy_key'] is None
    assert generation.history['partial']
    from app.models import JobStatus
    assert any(call.args[2] == JobStatus.COMPLETED for call in statuses.call_args_list)


def test_s3_history_uses_separate_namespace(monkeypatch):
    import boto3

    from app.services.storage import StorageService
    client = MagicMock()
    monkeypatch.setattr(boto3, 'client', lambda *args, **kwargs: client)
    storage = StorageService.__new__(StorageService)
    storage.storage_backend = 's3'
    run(storage.save_history_copy(b'jpeg', '7-hash.jpg'))
    assert client.put_object.call_args.kwargs['Key'] == 'history/7-hash.jpg'
    run(storage.delete_file('history', '7-hash.jpg'))
    assert client.delete_object.call_args.kwargs['Key'] == 'history/7-hash.jpg'


def test_azure_history_uses_separate_namespace():
    from app.services.storage import StorageService
    storage = StorageService.__new__(StorageService)
    storage.storage_backend = 'azure'
    storage._save_azure = AsyncMock(return_value='azure://images/history/7-hash.jpg')
    run(storage.save_history_copy(b'jpeg', '7-hash.jpg'))
    storage._save_azure.assert_awaited_once_with(b'jpeg', 'history/7-hash.jpg', 'image/jpeg')


def test_local_history_copy_storage(tmp_path):
    from app.services.storage import StorageService
    storage = StorageService.__new__(StorageService)
    storage.storage_backend, storage.local_path = 'local', tmp_path
    run(storage.save_history_copy(b'jpeg', '7-hash.jpg'))
    assert (tmp_path / 'history/7-hash.jpg').read_bytes() == b'jpeg'
    assert run(storage.delete_file('history', '7-hash.jpg'))
    assert not (tmp_path / 'history/7-hash.jpg').exists()


def test_used_by_route_requires_auth_and_returns_owned_count():
    app = FastAPI()
    app.include_router(routes.router, prefix='/api')
    db = db_mock()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        assert client.post('/api/images/used-by', json={'image_ids': [99]}).status_code in (401, 403)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=7)
        response = client.post('/api/images/used-by', json={'image_ids': [99]})
        assert response.status_code == 200
        assert response.json() == {'count': 0}


def test_owned_input_copy_route_only_serves_key_from_owned_history(monkeypatch):
    from starlette.responses import Response

    from app.services import storage as storage_module
    app = FastAPI()
    app.include_router(routes.router, prefix='/api')
    image = Image(id=8, user_id=7, history={'inputs': [{'copy_key': '7-hash.jpg'}]})
    db = db_mock(image)
    serve = MagicMock(return_value=Response(b'jpeg', media_type='image/jpeg'))
    monkeypatch.setattr(storage_module, 'get_storage_service', lambda: SimpleNamespace(history_copy_response=serve))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user_from_token_param] = lambda: SimpleNamespace(id=7)
    with TestClient(app) as client:
        assert client.get('/api/images/8/history/inputs/0').content == b'jpeg'
        assert client.get('/api/images/8/history/inputs/1').status_code == 404
    serve.assert_called_once_with('7-hash.jpg')


def test_recreated_lora_with_same_name_does_not_replace_snapshot_identity():
    old = SimpleNamespace(name='Dapple', base_model='flux-dev', trigger_word='dapple', created_at=datetime(2026, 1, 1))
    history = snapshot(db_mock(old), gen())
    replacement = SimpleNamespace(name='Dapple', created_at=datetime(2026, 10, 31))
    view = read_history(db_mock(replacement), Image(id=8, user_id=7, history=history))
    assert view['loras'][0]['deleted']
    assert view['loras'][0]['created_at'] == '2026-01-01T00:00:00'


def test_snapshot_failure_never_fails_the_job(monkeypatch):
    from types import SimpleNamespace

    from app.services import image_history

    monkeypatch.setattr(image_history, "snapshot", lambda *a: (_ for _ in ()).throw(ValueError("boom")))
    assert image_history.safe_snapshot(None, SimpleNamespace(id=1)) is None
