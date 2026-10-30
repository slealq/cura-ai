"""Settings and API surface derived from the model catalog."""
import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import settings as settings_api
from app.models.api_key import APIProvider
from app.services import billing_orchestrator
from app.services.model_catalog import (
    DEFAULT_EDIT_MODEL,
    DEFAULT_GENERATION_MODEL,
    DEFAULT_LANGUAGE_MODEL,
    IMAGE_MODELS,
    LANGUAGE_MODELS,
)
from app.services.settings_service import (
    DEFAULT_EDIT_CONFIGS,
    DEFAULT_GENERATION_CONFIGS,
    DEFAULT_PROVIDER_CONFIG,
    SettingsService,
)

USER = SimpleNamespace(id=1)


def run(coro):
    return asyncio.run(coro)


class StoredSettings(SettingsService):
    """SettingsService backed by a dict instead of the database."""

    def __init__(self, stored: dict[str, str]):
        self.stored = stored

    def get_setting(self, key, default=None):
        return self.stored.get(key, default)

    def set_setting(self, key, value, description=None):
        self.stored[key] = value


def test_provider_defaults_use_the_catalog():
    assert DEFAULT_PROVIDER_CONFIG["fal_vision_model"] == DEFAULT_LANGUAGE_MODEL == "anthropic/claude-haiku-5.5"
    assert DEFAULT_PROVIDER_CONFIG["fal_language_model"] == DEFAULT_LANGUAGE_MODEL
    for removed in ("vision_provider", "language_provider", "openai_vision_model", "anthropic_vision_model"):
        assert removed not in DEFAULT_PROVIDER_CONFIG
    assert DEFAULT_PROVIDER_CONFIG["vision_temperature"] == 1.0


def test_stale_stored_models_resolve_to_defaults_at_read_time():
    service = StoredSettings({"provider_config": json.dumps({
        "vision_provider": "openai",
        "openai_vision_model": "gpt-4o-mini",
        "fal_vision_model": "x-ai/grok-4-fast",
        "fal_language_model": "openai/gpt-6.1-sol",
        "max_tokens_tagging": 1234,
    })})

    config = service.get_provider_config()

    assert config["fal_vision_model"] == DEFAULT_LANGUAGE_MODEL
    assert config["fal_language_model"] == "openai/gpt-6.1-sol"
    assert config["max_tokens_tagging"] == 1234
    assert "vision_provider" not in config
    assert "openai_vision_model" not in config


def test_set_provider_config_drops_stale_keys():
    service = StoredSettings({"provider_config": json.dumps({"vision_provider": "openai", "fal_vision_model": "gone/model"})})
    service.set_provider_config({"max_tokens_tagging": 10})
    stored = json.loads(service.stored["provider_config"])
    assert "vision_provider" not in stored
    assert stored["fal_vision_model"] == DEFAULT_LANGUAGE_MODEL


def test_stored_default_generation_and_edit_models_self_heal():
    service = StoredSettings({"base_model": "flux-dev", "edit_model": "face-swap"})
    assert service.get_base_model() == DEFAULT_GENERATION_MODEL == "nano-banana-pro"
    assert service.get_edit_model() == DEFAULT_EDIT_MODEL == "nano-banana-2.1-edit"
    service = StoredSettings({"base_model": "flux-3", "edit_model": "kling-image"})
    assert (service.get_base_model(), service.get_edit_model()) == ("flux-3", "kling-image")


def test_per_model_settings_exist_for_every_catalog_model():
    for model in IMAGE_MODELS:
        configs = DEFAULT_GENERATION_CONFIGS if model.kind == "generate" else DEFAULT_EDIT_CONFIGS
        assert model.key in configs
    service = StoredSettings({})
    assert service.get_generation_config("flux-2")["guidance_scale"] == 2.5
    assert service.get_generation_config("nano-banana-lite")["aspect_ratio"] == "1:1"
    assert service.get_edit_config("kling-image")["resolution"] == "1K"
    assert service.get_edit_config()["aspect_ratio"] == "auto"  # default edit model
    service.set_generation_config({"width": 512}, "flux-2")
    assert json.loads(service.stored["generation_config:flux-2"])["width"] == 512


def test_provider_config_schemas_include_vision_temperature_and_drop_removed_fields():
    assert "vision_temperature" in settings_api.ProviderConfigResponse.model_fields
    assert "vision_temperature" in settings_api.ProviderConfigUpdateRequest.model_fields
    for removed in ("vision_provider", "language_provider", "openai_vision_model", "anthropic_language_model"):
        assert removed not in settings_api.ProviderConfigResponse.model_fields
    settings_api.ProviderConfigResponse(**DEFAULT_PROVIDER_CONFIG)


@pytest.mark.parametrize("field", ["fal_vision_model", "fal_language_model"])
def test_put_providers_rejects_unknown_models(field):
    with pytest.raises(HTTPException) as exc:
        run(settings_api.update_provider_config(
            settings_api.ProviderConfigUpdateRequest(**{field: "x-ai/grok-4-fast"}),
            db=MagicMock(), current_user=USER,
        ))
    assert exc.value.status_code == 400


def test_model_catalog_endpoint_shape():
    catalog = run(settings_api.get_model_catalog(current_user=USER))

    assert [m["id"] for m in catalog["language"]] == [m.id for m in LANGUAGE_MODELS]
    assert catalog["defaults"] == {
        "vision_model": "anthropic/claude-haiku-5.5",
        "language_model": "anthropic/claude-haiku-5.5",
        "generation_model": "nano-banana-pro",
        "edit_model": "nano-banana-2.1-edit",
    }
    assert {m["kind"] for m in catalog["generation"]} == {"generate"}
    assert {m["kind"] for m in catalog["edit"]} == {"edit"}
    assert [m["key"] for m in catalog["training_base_models"]] == ["flux-2", "qwen-image-2512"]
    lite = next(m for m in catalog["generation"] if m["key"] == "nano-banana-lite")
    assert "resolution" not in lite["params"] and "enable_web_search" not in lite["params"]
    json.dumps(catalog)


def test_models_endpoint_only_serves_openai_embeddings():
    for provider in ("anthropic", "fal", "nope"):
        with pytest.raises(HTTPException) as exc:
            run(settings_api.get_provider_models(provider, db=MagicMock(), current_user=USER))
        assert exc.value.status_code == 400
    assert not hasattr(settings_api, "CURATED_OPENAI_VISION_MODELS")
    assert not hasattr(settings_api, "_get_anthropic_models")
    assert not hasattr(settings_api, "_get_fal_models")


def test_storing_an_anthropic_key_is_a_400():
    for handler, kwargs in (
        (settings_api.save_api_key, {"request": settings_api.APIKeySaveRequest(key="sk-x")}),
        (settings_api.validate_api_key, {}),
    ):
        with pytest.raises(HTTPException) as exc:
            run(handler("anthropic", db=MagicMock(), current_user=USER, **kwargs))
        assert exc.value.status_code == 400
    assert APIProvider.ANTHROPIC.value == "anthropic"  # enum kept for stored rows


def test_api_key_service_has_no_anthropic_validation():
    from app.services.api_key_service import APIKeyService

    assert not hasattr(APIKeyService, "validate_anthropic_key")
    assert hasattr(APIKeyService, "validate_openai_key")


def test_decision_snapshot_carries_generation_params_for_the_pricing_fallback(monkeypatch):
    """Edit billing only passes generation_params; the orchestrator must record them in the snapshot."""
    db = MagicMock()
    orch = billing_orchestrator.BillingOrchestrator(db, user_id=1)
    monkeypatch.setattr(billing_orchestrator, "get_catalog_entry", lambda *a, **k: (None, "none"))
    monkeypatch.setattr("app.services.cost_calculator.estimate_sparks", lambda *a, **k: (Decimal("5"), None))
    monkeypatch.setattr(billing_orchestrator, "BillingService", MagicMock())
    params = {"edit_model": "seedream-5-pro-edit", "image_size": "square_hd"}

    decision, is_new = orch.create_decision(
        operation="edit", provider="fal", model="seedream-5-pro-edit", generation_params=params,
    )

    assert is_new
    assert decision.model == "bytedance/seedream/v5/pro/edit"
    assert decision.request_snapshot["generation_params"] == params

    # An explicit snapshot with its own generation_params is left alone.
    decision, _ = orch.create_decision(
        operation="generate", provider="fal", model="nano-banana-pro",
        generation_params={"resolution": "4K"}, request_snapshot={"generation_params": {"resolution": "2K"}, "x": 1},
    )
    assert decision.request_snapshot == {"generation_params": {"resolution": "2K"}, "x": 1}
