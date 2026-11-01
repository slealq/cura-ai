"""Layout semantics and precision validation without provider calls."""
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from jsonschema import validate
from PIL import Image
from pydantic import ValidationError

from app.api.edit import EditImageRequest, edit_images
from app.providers.fal_provider import FalEditor
from app.services.edit_layout import Box, ObjectBox, precision_box
from app.services.edit_mask import upright_base

SCHEMAS = json.loads((Path(__file__).parent / "fixtures" / "edit_layout_schemas.json").read_text())


def assert_payload_fits(endpoint, args):
    model, root = ("flux-3-klein-edit", "Flux3KleinEditImageInput") if "klein" in endpoint else ("ideogram-v4.5-edit", "V45EditInput")
    validate(args, {"$ref": f"#/components/schemas/{root}", "components": {"schemas": SCHEMAS[model]}})


RECT = dict(x_min=0.1, y_min=0.1, x_max=0.9, y_max=0.9)


def test_actions_map_to_published_fields_and_prompt_tags():
    objects = [dict(label=action.lower(), description="a bowl", action=action, source_box=RECT, target_box=RECT) for action in ("Place", "Move", "Remove")]
    endpoint, args = FalEditor(edit_model="flux-3-klein-edit").build_arguments(["base"], "A kitchen", object_boxes=objects)
    assert_payload_fits(endpoint, args)
    place, move, remove = args["bounding_boxes"]
    assert place == dict(label="place", description="a bowl", box=RECT)
    assert move["source_image_index"] == remove["source_image_index"] == 0
    assert move["target_box"] == RECT
    assert "target_box" not in remove and "box" not in remove
    assert all("action" not in box for box in args["bounding_boxes"])
    assert "Remove <remove>" in args["prompt"]


@pytest.mark.parametrize("patch", [dict(label="1bad"), dict(label="a" * 65), dict(description="x" * 501), dict(action="Move", source_box=None), dict(action="Place", target_box=None)])
def test_invalid_object_rejected(patch):
    with pytest.raises(ValidationError):
        ObjectBox.model_validate(dict(dict(label="bowl", description="bowl", action="Place", target_box=RECT), **patch))


@pytest.mark.parametrize("rect", [dict(RECT, x_min=-0.1), dict(RECT, x_max=2), dict(RECT, x_max=0.1), dict(RECT, y_min=float('nan'))])
def test_invalid_coordinates(rect):
    with pytest.raises(ValidationError):
        Box.model_validate(rect)


def test_precision_uses_upright_pixels_and_matches_schema():
    image = Image.new("RGB", (800, 400))
    exif = Image.Exif()
    exif[0x0112] = 6
    output = io.BytesIO()
    image.save(output, "JPEG", exif=exif)
    box = precision_box(RECT, upright_base(output.getvalue()))
    assert box == dict(x_min=40, x_max=360, y_min=80, y_max=720)
    endpoint, args = FalEditor(edit_model="ideogram-v4.5-edit").build_arguments(["base"], "change", precision_area="box", context_window_box=box)
    assert_payload_fits(endpoint, args)
    assert args["edit_precision"] == "high" and args["context_window"] == "none"
    with pytest.raises(ValueError, match="requires a mask"):
        FalEditor(edit_model="ideogram-v4.5-edit").build_arguments(["base"], "change", precision_area="auto")


@pytest.mark.parametrize("size", [(100, 100), (4000, 4000), (4000, 400)])
def test_precision_constraints(size):
    output = io.BytesIO()
    Image.new("RGB", size).save(output, "PNG")
    with pytest.raises(ValueError, match="Precision box"):
        precision_box(RECT, output.getvalue())


@pytest.mark.asyncio
async def test_api_rejects_wrong_models_and_incomplete_precision():
    for params in [dict(edit_model="flux-3-edit", object_boxes=[]), dict(edit_model="ideogram-v4.5-edit", precision_area="box"), dict(edit_model="ideogram-v4.5-edit", precision_area="box", mask_key="edit-sources/7-mask.png")]:
        with pytest.raises(HTTPException):
            await edit_images(EditImageRequest(prompt="change", source_image_ids=[1], **params), MagicMock(), SimpleNamespace(id=7))


@pytest.mark.parametrize("area", ["none", "auto", "box"])
def test_precision_history_records_context_without_mask_bytes(area):
    from datetime import datetime

    from app.models import GeneratedImage
    from app.services.image_history import snapshot

    params = dict(mode="edit", edit_model="ideogram-v4.5-edit", precision_area=area, mask_key="edit-sources/7-mask.png")
    if area == "box":
        params["context_window_box"] = dict(x_min=0, y_min=0, x_max=512, y_max=512)
    gen = GeneratedImage(id=1, user_id=7, prompt="change", base_model="ideogram-v4.5-edit", generation_provider="fal", created_at=datetime(2026, 10, 31), generation_params=params)
    history = snapshot(MagicMock(), gen, [{"copy_key": "base.jpg"}, {"role": "mask", "copy_key": "mask.png"}])
    assert history["settings"]["edit_precision"] == ("regular" if area == "none" else "high")
    assert history["settings"]["context_window"] == ("auto" if area == "auto" else "none")
    if area == "box":
        assert history["settings"]["context_window_box"] == params["context_window_box"]


@pytest.mark.asyncio
async def test_api_persists_layout_and_precision_in_existing_json(monkeypatch):
    from app.api import edit
    from app.services import image_service

    service = MagicMock()
    service.create_generated_image.return_value = SimpleNamespace(id=9)
    monkeypatch.setattr(edit, "get_generation_service", lambda *args: service)
    monkeypatch.setattr(image_service, "get_image_service", lambda *args: MagicMock())
    monkeypatch.setattr(edit, "dispatch_or_fail", lambda *args, **kwargs: SimpleNamespace(id="task"))
    db = MagicMock()
    db.refresh.side_effect = lambda job: setattr(job, "id", 10)
    objects = [dict(label="bowl", description="a bowl", action="Place", target_box=RECT)]
    for params in [dict(edit_model="flux-3-klein-edit", object_boxes=objects), dict(edit_model="ideogram-v4.5-edit", mask_key="edit-sources/7-mask.png", precision_area="box", precision_box=RECT)]:
        await edit_images(EditImageRequest(prompt="change", ordered_sources=[dict(type="gallery", id=3)], **params), db, SimpleNamespace(id=7))
        saved = service.create_generated_image.call_args.kwargs["generation_params"]
        for key, value in params.items():
            assert saved[key] == value


def test_history_preserves_mapped_boxes_and_action_prompt():
    from datetime import datetime

    from app.models import GeneratedImage
    from app.services.image_history import snapshot

    gen = GeneratedImage(id=1, user_id=7, prompt="kitchen", base_model="flux-3-klein-edit", generation_provider="fal", created_at=datetime(2026, 10, 31), generation_params=dict(mode="edit", edit_model="flux-3-klein-edit", object_boxes=[dict(label="bowl", description="a bowl", action="Remove", source_box=RECT)]))
    history = snapshot(MagicMock(), gen, [{"copy_key": "base.jpg"}])
    assert history["settings"]["bounding_boxes"][0]["source_box"] == RECT
    assert "Remove <bowl>" in history["prompt"]


def test_worker_rejects_small_precision_before_billing(monkeypatch):
    import base64
    from unittest.mock import AsyncMock

    from app.services import storage
    from app.workers import generation_tasks as tasks

    output = io.BytesIO()
    Image.new("RGB", (400, 400)).save(output, "PNG")
    base_uri = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode()
    mask = Image.new("L", (400, 400), 0)
    mask.paste(255, (1, 1, 20, 20))
    output = io.BytesIO()
    mask.save(output, "PNG")
    generation = SimpleNamespace(id=9, generation_params=dict(edit_model="ideogram-v4.5-edit", mask_key="edit-sources/7-mask.png", precision_area="box", precision_box=dict(x_min=0, y_min=0, x_max=0.1, y_max=0.1)))
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = generation
    monkeypatch.setattr(tasks, "_get_db", lambda: db)
    for name in ("_init_task_context", "_update_job_status", "write_log", "finalize_job_billing"):
        monkeypatch.setattr(tasks, name, MagicMock())
    monkeypatch.setattr(tasks, "get_generation_service", lambda *args: SimpleNamespace(get_generated_image=lambda _: generation))
    monkeypatch.setattr(tasks, "_resolve_edit_sources", lambda *args: [base_uri])
    monkeypatch.setattr(storage, "get_storage_service", lambda: SimpleNamespace(get_generated_image=AsyncMock(return_value=output.getvalue()), save_history_copy=AsyncMock()))
    billing, provider = MagicMock(), MagicMock()
    monkeypatch.setattr(tasks, "billable", billing)
    monkeypatch.setattr(tasks, "get_editor", provider)
    with pytest.raises(ValueError, match="Precision box"):
        tasks.edit_image.run(9, job_id=10, user_id=7)
    billing.assert_not_called()
    provider.assert_not_called()
