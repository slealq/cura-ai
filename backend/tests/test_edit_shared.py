"""Shared editing contracts, without provider or storage network calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.api.edit import EditImageRequest
from app.providers.fal_provider import build_image_request
from app.services.model_catalog import get_image_model, image_models
from app.workers import generation_tasks as tasks


def test_catalog_jobs_and_limits():
    for model in image_models('edit'):
        assert 'describe' in model.to_dict()['jobs']
        assert model.to_dict()['max_num_images'] >= 1
    for key, limit in [('qwen-image-3-edit', 3), ('grok-imagine-quality-edit', 3), ('grok-imagine-v2-edit', 4)]:
        assert get_image_model(key, 'edit').max_source_images == limit
    assert [m.key for m in image_models('edit') if 'objects' in m.jobs] == ['flux-3-klein-edit']
    assert [m.key for m in image_models('edit') if 'subject' in m.jobs] == ['kling-image']
    assert len([m for m in image_models('edit') if 'paint' in m.jobs]) == 4


def test_ideogram_base_and_references():
    model = get_image_model('ideogram-v4.5-edit', 'edit')
    _, payload = build_image_request(model, 'change', {}, source_urls=['base', 'ref2', 'ref1'])
    assert payload['image_url'] == 'base'
    assert payload['reference_image_urls'] == ['ref2', 'ref1']
    with pytest.raises(ValueError):
        build_image_request(model, 'change', {}, source_urls=['x'] * 6)


def test_optional_ordered_source_schema():
    assert EditImageRequest(source_image_ids=[1]).ordered_sources is None
    with pytest.raises(ValidationError):
        EditImageRequest(ordered_sources=[{'type': 'gallery'}])
    with pytest.raises(ValidationError):
        EditImageRequest(ordered_sources=[{'type': 'upload', 'key': '../private'}])


def test_mixed_order_is_kept_in_provider_and_history(monkeypatch):
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    image = SimpleNamespace(original_filename='library.png', object_key='library', mime_type='image/png')
    monkeypatch.setattr(tasks, 'get_image_service', lambda *args: SimpleNamespace(get_image=lambda _: image, get_image_data=AsyncMock(return_value=b'library')))
    generated = SimpleNamespace(object_key='generated', mime_type='image/png')
    monkeypatch.setattr(tasks, 'get_generation_service', lambda *args: SimpleNamespace(get_generated_image=lambda _: generated, get_generated_image_data=AsyncMock(return_value=b'generated')))
    from app.services import image_history, storage
    monkeypatch.setattr(storage, 'get_storage_service', lambda: SimpleNamespace(get_generated_image=AsyncMock(return_value=b'upload')))
    async def remember(storage, user_id, data, filename, source_key=None, **kwargs):
        return {'filename': filename, 'data': data}
    monkeypatch.setattr(image_history, 'input_snapshot', remember)
    monkeypatch.setattr(tasks, '_to_data_uri', lambda data, mime: data)
    history = []
    params = {'edit_model': 'kling-image', 'sources': {'ordered': [
        {'type': 'upload', 'key': 'edit-sources/u.png', 'name': 'u.png'},
        {'type': 'gallery', 'id': 2}, {'type': 'generated', 'id': 3}]}}
    assert tasks._resolve_edit_sources(db, params, 7, history) == [b'upload', b'library', b'generated']
    assert [entry['label'] for entry in history] == ['@Image1', '@Image2', '@Image3']
    assert history[0]['filename'] == 'u.png'
    assert tasks._resolve_edit_sources(db, {'sources': {'image_ids': [2], 'upload_keys': ['edit-sources/u.png']}}, 7) == [b'library', b'upload']


@pytest.mark.asyncio
async def test_api_persists_ordered_sources_and_legacy_groups(monkeypatch):
    from app.api import edit
    from app.services import image_service

    service = MagicMock()
    service.create_generated_image.return_value = SimpleNamespace(id=9)
    monkeypatch.setattr(edit, 'get_generation_service', lambda db, user_id: service)
    monkeypatch.setattr(image_service, 'get_image_service', lambda db, user_id: MagicMock())
    monkeypatch.setattr(edit, 'dispatch_or_fail', lambda *args, **kwargs: SimpleNamespace(id='task'))
    db = MagicMock()
    def refresh(job):
        job.id = 10
    db.refresh.side_effect = refresh
    ordered = [{'type': 'upload', 'key': 'edit-sources/u.png', 'name': 'Upload'}, {'type': 'gallery', 'id': 1}]
    await edit.edit_images(EditImageRequest(prompt='change', ordered_sources=ordered, source_generated_ids=[999]), db, SimpleNamespace(id=7))
    params = service.create_generated_image.call_args.kwargs['generation_params']
    assert params['sources']['ordered'] == ordered
    assert params['sources']['image_ids'] == [1]
    assert 'generated_ids' not in params['sources']
    service.reset_mock()
    await edit.edit_images(EditImageRequest(prompt='change', source_image_ids=[1]), db, SimpleNamespace(id=7))
    assert service.create_generated_image.call_args.kwargs['generation_params']['sources'] == {'image_ids': [1]}


@pytest.mark.asyncio
async def test_api_validates_source_ownership_and_limits(monkeypatch):
    from fastapi import HTTPException

    from app.api import edit
    from app.services import image_service

    service = MagicMock()
    service.get_image.return_value = None
    monkeypatch.setattr(image_service, 'get_image_service', lambda db, user_id: service)
    with pytest.raises(HTTPException) as error:
        await edit.edit_images(EditImageRequest(prompt='change', ordered_sources=[{'type': 'gallery', 'id': 55}]), MagicMock(), SimpleNamespace(id=7))
    assert error.value.status_code == 404
    for request in [EditImageRequest(prompt='change', edit_model='qwen-image-3-edit', source_image_ids=[1, 2, 3, 4]),
                    EditImageRequest(prompt='change', edit_model='flux-3-edit', source_image_ids=[1], num_images=2)]:
        with pytest.raises(HTTPException) as error:
            await edit.edit_images(request, MagicMock(), SimpleNamespace(id=7))
        assert error.value.status_code == 400


def test_estimate_uses_edit_pricing(monkeypatch):
    from app.api import billing
    from app.services import cost_calculator

    resolve = MagicMock(return_value=('fal', 'edit-endpoint', 'edit'))
    estimate = MagicMock(return_value=(42, {}))
    monkeypatch.setattr(cost_calculator, 'resolve_catalog_model', resolve)
    monkeypatch.setattr(billing, '_estimate_sparks', estimate)
    result = billing.estimate_generation_cost(billing.GenerationEstimateRequest(base_model='kling-image', operation='edit', resolution='4K'), SimpleNamespace(id=7), MagicMock())
    assert result['estimated_sparks'] == 42
    resolve.assert_called_once_with('fal', 'kling-image', 'edit', with_lora=False)
    assert estimate.call_args.kwargs['generation_params'] == {'resolution': '4K'}
    assert billing.GenerationEstimateRequest(base_model='flux-3').operation == 'generate'
