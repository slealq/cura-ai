"""Paint validation and provider payloads, entirely offline."""
import base64
import io
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from PIL import Image
from test_model_catalog_schema import assert_payload_fits

from app.api.edit import EditImageRequest, edit_images
from app.models import GeneratedImage
from app.providers.fal_provider import FalEditor
from app.services.edit_mask import PAINT_MODELS, prepare_mask
from app.services.image_history import input_snapshot, snapshot


def png(values=(0, 255), size=(2, 1), mode="L"):
    image = Image.new(mode, size)
    image.putdata(values)
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def uri(data):
    return "data:image/png;base64," + base64.b64encode(data).decode()


@pytest.mark.parametrize("model", sorted(PAINT_MODELS))
def test_mask_payload_matches_schema_and_polarity(model):
    data = prepare_mask(png(), png(), model, 2)
    endpoint, args = FalEditor(edit_model=model).build_arguments(["base", "reference"], "change", mask_url=uri(data))
    assert_payload_fits(endpoint, args)
    mask = Image.open(io.BytesIO(base64.b64decode(args["mask_url"].split(",")[1])))
    assert list(mask.getdata()) == ([255, 0] if model == "ideogram-v4.5-edit" else [0, 255])
    if model == "ideogram-v4.5-edit":
        assert args["image_url"] == "base"
        assert args["reference_image_urls"] == ["reference"]


@pytest.mark.parametrize("model", sorted(PAINT_MODELS))
def test_dimension_and_empty_mask_validation(model):
    with pytest.raises(ValueError, match="dimensions"):
        prepare_mask(png(), png((0,), (1, 1)), model, 1)
    with pytest.raises(ValueError, match="Paint an area"):
        prepare_mask(png((0, 0)), png(), model, 1)


def test_ideogram_requires_preserved_pixels_and_three_reference_limit():
    with pytest.raises(ValueError, match="unpainted"):
        prepare_mask(png((255, 255)), png(), "ideogram-v4.5-edit", 1)
    with pytest.raises(ValueError, match="three references"):
        prepare_mask(png(), png(), "ideogram-v4.5-edit", 5)
    prepare_mask(png(), png(), "ideogram-v4.5-edit", 4)
    prepare_mask(png((255, 255)), png(), "gpt-image-2-edit", 16)
    with pytest.raises(ValueError, match="automatic output"):
        FalEditor(edit_model="ideogram-v4.5-edit").build_arguments(["base"], "change", image_size="square", mask_url=uri(png()))


def test_unsupported_model_and_transparent_masks_rejected():
    with pytest.raises(ValueError, match="does not support"):
        prepare_mask(png(), png(), "flux-3-edit", 1)
    with pytest.raises(ValueError, match="opaque"):
        prepare_mask(png(((255, 255, 255, 0), (0, 0, 0, 255)), mode="RGBA"), png(), "gpt-image-2-edit", 1)


@pytest.mark.asyncio
async def test_api_rejects_other_users_mask_and_ideogram_source_overflow():
    for kwargs in [dict(mask_key="edit-sources/8-mask.png", edit_model="gpt-image-2-edit"),
                   dict(mask_key="edit-sources/7-mask.png", edit_model="flux-3-edit"),
                   dict(mask_key="edit-sources/7-mask.png", edit_model="ideogram-v4.5-edit", source_image_ids=[1, 2, 3, 4, 5]),
                   dict(mask_key="edit-sources/7-mask.png", edit_model="ideogram-v4.5-edit", image_size="square")]:
        request = EditImageRequest(prompt="change", **dict(source_image_ids=[1], **{k: v for k, v in kwargs.items() if k != "source_image_ids"}))
        if "source_image_ids" in kwargs:
            request.source_image_ids = kwargs["source_image_ids"]
        with pytest.raises(HTTPException) as error:
            await edit_images(request, MagicMock(), SimpleNamespace(id=7))
        assert error.value.status_code == 400


@pytest.mark.asyncio
async def test_mask_history_is_lossless_and_does_not_count_as_reference():
    storage = SimpleNamespace(save_history_copy=AsyncMock())
    data = png()
    item = await input_snapshot(storage, 7, data, "mask.png", role="mask", uploaded=True)
    item["label"] = "Painted area"
    assert item["copy_key"].endswith("-mask.png")
    saved = storage.save_history_copy.call_args.args[0]
    assert list(Image.open(io.BytesIO(saved)).getdata()) == [0, 255]
    gen = GeneratedImage(id=1, user_id=7, prompt="change", base_model="ideogram-v4.5-edit", generation_provider="fal", created_at=datetime(2026, 10, 31),
                         generation_params={"mode": "edit", "edit_model": "ideogram-v4.5-edit", "mask_key": "edit-sources/7-mask.png"})
    inputs = [{"copy_key": "base.jpg"}] * 4 + [item]
    history = snapshot(MagicMock(), gen, inputs)
    assert history["inputs"][-1]["role"] == "mask"
    assert history["partial"] is False


@pytest.mark.asyncio
async def test_api_keeps_mask_and_order_in_generation_params(monkeypatch):
    from app.api import edit
    from app.services import image_service

    service = MagicMock()
    service.create_generated_image.return_value = SimpleNamespace(id=9)
    monkeypatch.setattr(edit, "get_generation_service", lambda *args: service)
    monkeypatch.setattr(image_service, "get_image_service", lambda *args: MagicMock())
    monkeypatch.setattr(edit, "dispatch_or_fail", lambda *args, **kwargs: SimpleNamespace(id="task"))
    db = MagicMock()
    db.refresh.side_effect = lambda job: setattr(job, "id", 10)
    ordered = [{"type": "gallery", "id": 3}, {"type": "gallery", "id": 2}]
    await edit_images(EditImageRequest(prompt="change", edit_model="ideogram-v4.5-edit", mask_key="edit-sources/7-mask.png", ordered_sources=ordered), db, SimpleNamespace(id=7))
    params = service.create_generated_image.call_args.kwargs["generation_params"]
    assert params["mask_key"] == "edit-sources/7-mask.png"
    assert params["sources"]["ordered"] == ordered


def test_worker_rejects_wrong_dimensions_before_billing_or_provider(monkeypatch):
    from app.services import storage
    from app.workers import generation_tasks as tasks

    generation = SimpleNamespace(id=9, generation_params={"edit_model": "gpt-image-2-edit", "mask_key": "edit-sources/7-mask.png"})
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = generation
    service = SimpleNamespace(get_generated_image=lambda _: generation)
    monkeypatch.setattr(tasks, "_get_db", lambda: db)
    monkeypatch.setattr(tasks, "_init_task_context", MagicMock())
    monkeypatch.setattr(tasks, "_update_job_status", MagicMock())
    monkeypatch.setattr(tasks, "write_log", MagicMock())
    monkeypatch.setattr(tasks, "finalize_job_billing", MagicMock())
    monkeypatch.setattr(tasks, "get_generation_service", lambda *args: service)
    monkeypatch.setattr(tasks, "_resolve_edit_sources", lambda *args: [uri(png())])
    monkeypatch.setattr(storage, "get_storage_service", lambda: SimpleNamespace(get_generated_image=AsyncMock(return_value=png((255,), (1, 1)))))
    provider = MagicMock()
    billing = MagicMock()
    monkeypatch.setattr(tasks, "get_editor", provider)
    monkeypatch.setattr(tasks, "billable", billing)
    with pytest.raises(ValueError, match="dimensions"):
        tasks.edit_image.run(9, job_id=10, user_id=7)
    provider.assert_not_called()
    billing.assert_not_called()
    assert "dimensions" in generation.error_message


def test_rotated_phone_photo_matches_a_mask_painted_upright():
    import io

    from PIL import Image

    from app.services.edit_mask import prepare_mask, upright_base

    base = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[0x0112] = 6
    raw = io.BytesIO()
    base.save(raw, format="JPEG", exif=exif)
    upright = upright_base(raw.getvalue())
    assert Image.open(io.BytesIO(upright)).size == (20, 40)
    mask = Image.new("L", (20, 40), 255)
    mask.paste(0, (0, 0, 5, 5))
    out = io.BytesIO()
    mask.save(out, format="PNG")
    assert prepare_mask(out.getvalue(), upright, "gpt-image-2-edit", 1)
