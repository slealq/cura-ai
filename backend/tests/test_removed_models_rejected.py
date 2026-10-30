"""Removed / unknown models are rejected loudly, and table pricing matches the catalog."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import edit as edit_api
from app.api import generation as generation_api
from app.api import vision as vision_api
from app.api.model_validation import validate_model_params
from app.models.lora_model import LoraModelStatus
from app.providers.fal_provider import FalEditor, FalGenerator, FalTrainer
from app.services.model_catalog import IMAGE_MODELS, get_image_model
from app.services.pricing_engine import compute_raw_cost

USER = SimpleNamespace(id=1)
REMOVED_GENERATE = ["flux-dev", "qwen-2.5", "nano-banana-2", "not-a-model"]
REMOVED_EDIT = ["qwen-image-max-edit", "qwen-image-2-pro-edit", "wan-25", "grok-imagine", "face-swap", "not-a-model"]
REMOVED_VISION = ["x-ai/grok-4-fast", "qwen/qwen3-vl-235b-a22b-instruct", "google/gemini-2.5-flash", "gpt-4o-mini", "nope"]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def gen_service(monkeypatch):
    service = MagicMock()
    monkeypatch.setattr(generation_api, "get_generation_service", lambda db, user_id: service)
    return service


def _lora(base_model, **overrides):
    values = dict(
        id=5, name="style", status=LoraModelStatus.COMPLETED, lora_url="https://example.com/x.safetensors",
        base_model=base_model,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("model", REMOVED_GENERATE)
def test_generate_rejects_removed_and_unknown_models(gen_service, model):
    with pytest.raises(HTTPException) as exc:
        run(generation_api.generate_images(
            generation_api.GenerateRequest(prompt="a fox", base_model=model), db=MagicMock(), current_user=USER,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail == "model no longer supported"


@pytest.mark.parametrize("model", REMOVED_EDIT)
def test_edit_rejects_removed_and_unknown_models(model):
    with pytest.raises(HTTPException) as exc:
        run(edit_api.edit_images(
            edit_api.EditImageRequest(prompt="x", edit_model=model, source_image_ids=[1]),
            db=MagicMock(), current_user=USER,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail == "model no longer supported"


@pytest.mark.parametrize("model", REMOVED_VISION)
def test_vision_rejects_removed_and_unknown_models(model):
    with pytest.raises(HTTPException) as exc:
        run(vision_api.analyze_image(
            vision_api.VisionAnalyzeRequest(source_image_id=1, model=model), db=MagicMock(), current_user=USER,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail == "model no longer supported"


def test_vision_ignores_legacy_provider_field():
    request = vision_api.VisionAnalyzeRequest(source_image_id=1, provider="anthropic")
    assert request.provider == "anthropic"  # accepted, never used


@pytest.mark.parametrize("model", REMOVED_GENERATE)
def test_fal_generator_raises_on_unknown_model(model):
    with pytest.raises(ValueError):
        FalGenerator(base_model=model)


@pytest.mark.parametrize("model", REMOVED_EDIT)
def test_fal_editor_raises_on_unknown_model(model):
    with pytest.raises(ValueError):
        FalEditor(edit_model=model)


def test_fal_trainer_raises_on_unknown_base_model_but_reads_legacy_rows():
    with pytest.raises(ValueError):
        FalTrainer(base_model="not-a-model")
    assert FalTrainer(base_model="flux-dev").config["training_endpoint"] == "fal-ai/flux-lora-fast-training"
    assert FalTrainer(base_model="qwen-2.5").config["training_endpoint"] == "fal-ai/qwen-image-2512-trainer-v2"


def test_loras_on_a_model_without_lora_support_are_rejected_by_the_api(gen_service):
    gen_service.get_lora_model.return_value = _lora("nano-banana-pro")
    with pytest.raises(HTTPException) as exc:
        run(generation_api.generate_images(
            generation_api.GenerateRequest(
                prompt="a fox", base_model="nano-banana-pro", loras=[generation_api.LoraInput(lora_model_id=5)],
            ),
            db=MagicMock(), current_user=USER,
        ))
    assert exc.value.status_code == 400
    assert "LoRA" in exc.value.detail


def test_generation_with_a_legacy_lora_row_is_rejected(gen_service):
    gen_service.get_lora_model.return_value = _lora("flux-dev")
    with pytest.raises(HTTPException) as exc:
        run(generation_api.generate_images(
            generation_api.GenerateRequest(prompt="a fox", loras=[generation_api.LoraInput(lora_model_id=5)]),
            db=MagicMock(), current_user=USER,
        ))
    assert exc.value.status_code == 400
    assert exc.value.detail == "model no longer supported"


def test_generator_never_silently_drops_loras():
    with pytest.raises(ValueError):
        FalGenerator(base_model="nano-banana-pro").build_arguments("x", loras=[{"path": "p", "scale": 1}])


def test_invalid_option_for_a_supported_param_is_a_400(gen_service):
    with pytest.raises(HTTPException) as exc:
        run(generation_api.generate_images(
            generation_api.GenerateRequest(prompt="a fox", base_model="nano-banana-pro", resolution="9K"),
            db=MagicMock(), current_user=USER,
        ))
    assert exc.value.status_code == 400
    assert "resolution" in exc.value.detail


def test_param_the_model_does_not_support_is_ignored():
    lite = get_image_model("nano-banana-lite", "generate")
    accepted = validate_model_params(lite, {"resolution": "2K", "enable_web_search": True, "aspect_ratio": "16:9"})
    assert accepted == {"aspect_ratio": "16:9"}


def test_custom_size_dict_is_only_valid_where_declared():
    flux = get_image_model("flux-2-lora-edit", "edit")
    assert validate_model_params(flux, {"image_size": {"width": 512, "height": 512}}) == {"image_size": {"width": 512, "height": 512}}
    gpt = get_image_model("gpt-image-2-edit", "edit")
    with pytest.raises(HTTPException):
        validate_model_params(gpt, {"image_size": {"width": 512, "height": 512}})


def test_every_offered_edit_and_generation_key_passes_the_allowlist():
    assert {m.key for m in IMAGE_MODELS if m.kind == "edit"} == edit_api.SUPPORTED_EDIT_MODELS
    assert generation_api.SUPPORTED_BASE_MODELS == {"flux-2", "qwen-image-2512"}


# --- Table pricing ---

_TABLE_MODELS = [m for m in IMAGE_MODELS if m.price_table]


@pytest.mark.parametrize(
    ("model", "option"),
    [pytest.param(m, option, id=f"{m.key}:{option}") for m in _TABLE_MODELS for option in m.price_table],
)
def test_table_pricing_gives_each_option_its_price(model, option):
    cost = compute_raw_cost("fal", model.endpoint, model.kind, {model.price_param: option})
    assert cost == Decimal(str(model.price_table[option]))


@pytest.mark.parametrize("model", _TABLE_MODELS, ids=lambda m: m.key)
def test_table_pricing_defaults_to_the_catalog_default_option(model):
    assert compute_raw_cost("fal", model.endpoint, model.kind, {}) == Decimal(str(model.base_price))


def test_table_pricing_known_values():
    assert compute_raw_cost("fal", "openai/gpt-image-2.5/flare/text-to-image", "generate", {"quality": "max"}) == Decimal("0.21072")
    assert compute_raw_cost("fal", "bytedance/seedream/v5/pro/edit", "edit", {"image_size": "square_hd"}) == Decimal("0.0675")
    assert compute_raw_cost("fal", "bytedance/seedream/v5/pro/edit", "edit", {}) == Decimal("0.135")
    assert compute_raw_cost("fal", "xai/grok-imagine-image/v2.0/edit", "edit", {"resolution": "2k"}) == Decimal("0.09")
    assert compute_raw_cost("fal", "fal-ai/kling-image/o3/image-to-image", "edit", {"resolution": "4K"}) == Decimal("0.056")
    assert compute_raw_cost("fal", "google/nano-banana-2.1/edit", "edit", {"resolution": "4K"}) == Decimal("0.138")


def test_existing_strategies_still_apply_and_flat_models_have_none():
    assert compute_raw_cost("fal", "fal-ai/nano-banana-pro", "generate", {"resolution": "4K"}) == Decimal("0.30")
    assert compute_raw_cost("fal", "fal-ai/flux-2-pro", "generate", {"image_size": "square_hd"}) == Decimal("0.03")
    assert compute_raw_cost("fal", "fal-ai/flux-2-max", "generate", {}) is None
    assert compute_raw_cost("fal", "fal-ai/flux-2", "generate", {}) is None


def test_table_pricing_ignores_lora_endpoints_and_wrong_operations():
    assert compute_raw_cost("fal", "fal-ai/flux-2/lora", "generate", {}) is None
    assert compute_raw_cost("fal", "google/nano-banana-2.1", "edit", {"resolution": "4K"}) is None
