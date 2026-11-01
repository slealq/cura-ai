"""Offline Kling payload, ordered identity, series dispatch and pricing contracts."""
import io
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from jsonschema import validate
from PIL import Image

from app.api.edit import EditImageRequest, edit_images
from app.providers.fal_provider import FalEditor
from app.services.edit_subject import subject_inputs, validate_subject_media
from app.services.image_history import snapshot
from app.services.pricing_engine import compute_raw_cost

SOURCES = [
    dict(type="upload", key="edit-sources/7-main.png", role="element_main", element=1),
    dict(type="gallery", id=2, role="reference"),
    dict(type="generated", id=3, role="element_angle", element=1),
]


def test_roles_survive_reorder_and_fit_schema():
    schema = json.loads((Path(__file__).parent / "fixtures/edit_subject_schema.json").read_text())
    root = next(name for name, value in schema.items() if "result_type" in value.get("properties", {}))
    for indices in [[0, 1, 2], [2, 0, 1]]:
        sources = [SOURCES[i] for i in indices]
        urls = [["main", "composition", "angle"][i] for i in indices]
        _, args = FalEditor(edit_model="kling-image").build_arguments(urls, "@Element1 with @Image1", subject_sources=sources, result_type="series", series_amount=9)
        validate(args, {"$ref": f"#/components/schemas/{root}", "components": {"schemas": schema}})
        assert args["image_urls"] == ["composition"]
        assert args["elements"] == [dict(frontal_image_url="main", reference_image_urls=["angle"])]
        assert args["num_images"] == 1 and args["series_amount"] == 9


@pytest.mark.parametrize("sources", [
    [SOURCES[2]], [SOURCES[0], SOURCES[0]], [SOURCES[0]] + [SOURCES[2]] * 4,
    [dict(SOURCES[0], element=2)], [dict(SOURCES[1], element=1)], [SOURCES[1]] * 11,
])
def test_invalid_elements_and_reference_limits(sources):
    with pytest.raises(ValueError):
        subject_inputs(sources, ["input"] * len(sources))


@pytest.mark.parametrize("size", [(299, 500), (300, 900), (900, 300)])
def test_media_rejected(size):
    output = io.BytesIO()
    Image.new("RGB", size).save(output, "PNG")
    with pytest.raises(ValueError):
        validate_subject_media(output.getvalue())


@pytest.mark.parametrize("patch", [dict(edit_model="flux-3-edit", result_type="single"), dict(result_type="series"), dict(series_amount=2), dict(result_type="series", series_amount=3, num_images=2), dict(prompt="x" * 2501)])
@pytest.mark.asyncio
async def test_api_rejects_invalid_subject_requests(patch):
    values = dict(prompt="change", edit_model="kling-image", ordered_sources=SOURCES)
    values.update(patch)
    with pytest.raises(HTTPException):
        await edit_images(EditImageRequest(**values), MagicMock(), SimpleNamespace(id=7))


@pytest.mark.asyncio
async def test_series_creates_all_records_but_dispatches_once(monkeypatch):
    from app.api import edit
    from app.services import image_service
    service = MagicMock()
    service.create_generated_image.side_effect = [SimpleNamespace(id=i) for i in [10, 11, 12]]
    monkeypatch.setattr(edit, "get_generation_service", lambda *args: service)
    monkeypatch.setattr(image_service, "get_image_service", lambda *args: MagicMock())
    dispatch = MagicMock(return_value=SimpleNamespace(id="task"))
    monkeypatch.setattr(edit, "dispatch_or_fail", dispatch)
    db = MagicMock()
    db.refresh.side_effect = lambda job: setattr(job, "id", 8)
    result = await edit_images(EditImageRequest(prompt="change", edit_model="kling-image", ordered_sources=SOURCES, result_type="series", series_amount=3), db, SimpleNamespace(id=7))
    assert result.generated_image_ids == [10, 11, 12]
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["series_ids"] == [10, 11, 12]
    assert dispatch.call_args.args[1].total_items == 3
    params = service.create_generated_image.call_args.kwargs["generation_params"]
    assert params["sources"]["ordered"] == SOURCES
    assert params["series_amount"] == 3


@pytest.mark.parametrize("resolution,unit", [("1K", "0.028"), ("2K", "0.028"), ("4K", "0.056")])
@pytest.mark.parametrize("count", [2, 9])
def test_series_pricing_multiplies_once(resolution, unit, count):
    endpoint = "fal-ai/kling-image/o3/image-to-image"
    assert compute_raw_cost("fal", endpoint, "edit", dict(resolution=resolution, result_type="series", series_amount=count)) == Decimal(unit) * count
    assert compute_raw_cost("fal", endpoint, "edit", dict(resolution=resolution)) == Decimal(unit)


def test_history_keeps_element_settings_and_inputs():
    from app.models import GeneratedImage
    params = dict(mode="edit", edit_model="kling-image", sources=dict(ordered=SOURCES), result_type="series", series_amount=3)
    generation = GeneratedImage(id=1, user_id=7, prompt="@Element1", base_model="kling-image", generation_provider="fal", created_at=datetime(2026, 10, 31), generation_params=params)
    inputs = [dict(copy_key="saved.jpg", role=source["role"], element=source.get("element")) for source in SOURCES]
    history = snapshot(MagicMock(), generation, inputs)
    assert history["inputs"] == inputs
    assert history["settings"]["elements"][0]["frontal_image_url"] == "input"
    assert history["settings"]["series_amount"] == 3


@pytest.mark.parametrize("returned", [2, 3, 4])
def test_series_worker_saves_every_result_once(monkeypatch, returned):
    from app.models import GenerationStatus
    from app.workers import generation_tasks as tasks
    params = dict(edit_model="kling-image", mode="edit", result_type="series", series_amount=3)
    generations = {i: SimpleNamespace(id=i, prompt="subject", negative_prompt=None, base_model="kling-image", generation_params=params.copy(), history=None, status=GenerationStatus.PENDING) for i in [1, 2, 3, 4]}
    save = AsyncMock()
    service = SimpleNamespace(get_generated_image=lambda i: generations[i], save_generated_result=save, create_generated_image=lambda **kwargs: generations[4])
    db = MagicMock()
    monkeypatch.setattr(tasks, "_get_db", lambda: db)
    for name in ["_init_task_context", "_update_job_status", "write_log", "finalize_job_billing"]:
        monkeypatch.setattr(tasks, name, MagicMock())
    monkeypatch.setattr(tasks, "get_generation_service", lambda *args: service)
    monkeypatch.setattr(tasks, "_resolve_edit_sources", lambda *args: ["data:image/png;base64,eA=="])
    monkeypatch.setattr("app.services.edit_subject.validate_subject_media", lambda data: None)
    result = SimpleNamespace(images=[b"image"] * returned, widths=[512] * returned, heights=[512] * returned, seed=1, metadata={})
    editor = SimpleNamespace(edit=AsyncMock(return_value=result))
    monkeypatch.setattr(tasks, "get_editor", lambda **kwargs: editor)
    billing = MagicMock()
    billing.__enter__.return_value = billing
    billing.skipped = False
    billing.call.side_effect = lambda fn, *args: fn(*args)
    monkeypatch.setattr(tasks, "billable", lambda *args, **kwargs: billing)
    monkeypatch.setattr("app.services.image_history.safe_snapshot", lambda *args: dict(inputs=[]))
    tasks.edit_image.run(1, job_id=8, user_id=7, series_ids=[1, 2, 3])
    editor.edit.assert_called_once()
    assert editor.edit.call_args.kwargs["series_amount"] == 3
    assert save.await_count == returned
    assert [call.kwargs["generated_image_id"] for call in save.call_args_list] == list(range(1, returned + 1))
    assert all(generations[i].history for i in range(1, returned + 1))
    if returned == 2:
        assert generations[3].status == GenerationStatus.FAILED


def test_estimate_sends_series_total_to_shared_pricing(monkeypatch):
    from app.api import billing
    estimate = MagicMock(return_value=(252, {}))
    monkeypatch.setattr(billing, "_estimate_sparks", estimate)
    result = billing.estimate_generation_cost(billing.GenerationEstimateRequest(base_model="kling-image", operation="edit", result_type="series", series_amount=9, resolution="4K"), SimpleNamespace(id=7), MagicMock())
    assert result["estimated_sparks"] == 252
    assert estimate.call_args.kwargs["generation_params"] == dict(result_type="series", series_amount=9, resolution="4K")


def test_resolver_retains_roles_and_labels_after_mixed_source_reorder(monkeypatch):
    from app.services import image_history, storage
    from app.workers import generation_tasks as tasks
    db = MagicMock()
    db.query.return_value.filter_by.return_value.first.return_value = None
    image = SimpleNamespace(original_filename="composition.png", object_key="composition", mime_type="image/png")
    monkeypatch.setattr(tasks, "get_image_service", lambda *args: SimpleNamespace(get_image=lambda _: image, get_image_data=AsyncMock(return_value=b"composition")))
    generated = SimpleNamespace(object_key="angle", mime_type="image/png")
    monkeypatch.setattr(tasks, "get_generation_service", lambda *args: SimpleNamespace(get_generated_image=lambda _: generated, get_generated_image_data=AsyncMock(return_value=b"angle")))
    monkeypatch.setattr(storage, "get_storage_service", lambda: SimpleNamespace(get_generated_image=AsyncMock(return_value=b"main")))
    async def remember(storage, user_id, data, filename, source_key=None, **kwargs):
        return dict(copy_key="saved.jpg", filename=filename, source_key=source_key)
    monkeypatch.setattr(image_history, "input_snapshot", remember)
    monkeypatch.setattr(tasks, "_to_data_uri", lambda data, mime: data)
    ordered = [SOURCES[2], SOURCES[1], SOURCES[0]]
    inputs = []
    urls = tasks._resolve_edit_sources(db, dict(edit_model="kling-image", sources=dict(ordered=ordered)), 7, inputs)
    assert urls == [b"angle", b"composition", b"main"]
    assert [item["role"] for item in inputs] == ["element_angle", "reference", "element_main"]
    assert [item["label"] for item in inputs] == ["@Element1 · angle", "@Image1", "@Element1 · main"]
    assert subject_inputs(ordered, urls)[1][0]["frontal_image_url"] == b"main"


@pytest.mark.asyncio
async def test_series_history_allocates_one_charge_across_library_results():
    from app.models import GenerationStatus
    from app.services.generation_service import GenerationService
    db = MagicMock()
    storage = SimpleNamespace(save_generated_image=AsyncMock(), generate_generated_thumbnails=AsyncMock(return_value={}))
    service = GenerationService(db, 7)
    service.storage = storage
    service.add_to_library = AsyncMock()
    for index in range(1, 4):
        gen = SimpleNamespace(id=index, generation_params=dict(series_billing_resource=1, series_output_count=3), history=dict(inputs=[]))
        db.query.return_value.filter.return_value.first.return_value = gen
        db.query.return_value.join.return_value.filter.return_value.scalar.return_value = Decimal("0.084")
        result = await service.save_generated_result(index, b"image", 512, 512)
        assert result.status == GenerationStatus.COMPLETED
        assert result.history["charged_cost"] == pytest.approx(0.028)
    assert service.add_to_library.await_count == 3


@pytest.mark.parametrize("cancelled", [False, True])
def test_series_failure_settles_all_placeholders(monkeypatch, cancelled):
    from app.models import GenerationStatus, JobStatus
    from app.workers import generation_tasks as tasks
    generations = {i: SimpleNamespace(id=i, prompt="subject", negative_prompt=None, generation_params=dict(edit_model="kling-image", result_type="series", series_amount=3), status=GenerationStatus.PENDING) for i in [1, 2, 3]}
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = generations[1]
    service = SimpleNamespace(get_generated_image=lambda i: generations[i])
    monkeypatch.setattr(tasks, "_get_db", lambda: db)
    monkeypatch.setattr(tasks, "get_generation_service", lambda *args: service)
    for name in ["_init_task_context", "_update_job_status", "write_log", "finalize_job_billing"]:
        monkeypatch.setattr(tasks, name, MagicMock())
    if cancelled:
        db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(status=JobStatus.CANCELLED)
        monkeypatch.setattr(tasks, "_resolve_edit_sources", lambda *args: ["data:image/png;base64,eA=="])
        monkeypatch.setattr("app.services.edit_subject.validate_subject_media", lambda data: None)
    else:
        def fail(*args):
            raise ValueError("Missing source")
        monkeypatch.setattr(tasks, "_resolve_edit_sources", fail)
    editor = MagicMock()
    monkeypatch.setattr(tasks, "get_editor", editor)
    billing = MagicMock()
    monkeypatch.setattr(tasks, "billable", billing)
    if cancelled:
        assert tasks.edit_image.run(1, job_id=8, user_id=7, series_ids=[1, 2, 3])["status"] == "cancelled"
    else:
        with pytest.raises(ValueError, match="Missing source"):
            tasks.edit_image.run(1, job_id=8, user_id=7, series_ids=[1, 2, 3])
    assert all(gen.status == GenerationStatus.FAILED for gen in generations.values())
    editor.assert_not_called()
    billing.assert_not_called()


def test_subject_without_references_still_sends_required_image_urls():
    from app.services.edit_subject import subject_inputs

    sources = [{"role": "element_main", "element": 1}, {"role": "element_angle", "element": 1}]
    references, elements = subject_inputs(sources, ["main", "angle"])
    assert references == ["main"]
    assert elements == [{"frontal_image_url": "main", "reference_image_urls": ["angle"]}]
