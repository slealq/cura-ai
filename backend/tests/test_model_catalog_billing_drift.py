"""Keep the model catalog and migration 055's billing rows in sync.

The migration holds its own literal data (it must not import app code), so these
tests are the only thing tying the two together.
"""
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from app.services import model_registry
from app.services.model_catalog import (
    IMAGE_MODELS,
    LANGUAGE_MODELS,
    LANGUAGE_OPERATIONS,
    LEGACY_TRAINER_ENDPOINTS,
    offered_keys,
)

_MIGRATION = Path(__file__).parent.parent / "migrations" / "versions" / "055_refresh_model_catalog.py"
_spec = importlib.util.spec_from_file_location("migration_055", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)

REMOVED_IMAGE_KEYS = {
    "flux-dev", "qwen-2.5", "nano-banana-2", "nano-banana-2.1", "nano-banana-pro-edit",
    "qwen-image-max-edit", "qwen-image-2-pro-edit", "wan-25", "grok-imagine", "face-swap",
}
REMOVED_LANGUAGE_IDS = {
    "x-ai/grok-4.7", "qwen/qwen3.8-flash", "qwen/qwen3.8-max-0902", "qwen/qwen3.8-max-prime",
    "x-ai/grok-4-fast", "x-ai/grok-2-vision-1212", "qwen/qwen3-vl-235b-a22b-instruct", "google/gemini-2.5-flash",
}


def _image_rows() -> dict[tuple[str, str], tuple[float, str | None]]:
    return {(m, op): (cost, rules) for m, op, cost, rules in migration.IMAGE_ROWS}


def test_migration_chain_and_operations():
    assert migration.down_revision == "054_add_frontier_fal_models"
    assert tuple(migration.LANGUAGE_OPERATIONS) == LANGUAGE_OPERATIONS


def test_every_language_model_is_in_the_migration():
    assert set(migration.LANGUAGE_RATES) == {m.id for m in LANGUAGE_MODELS}


@pytest.mark.parametrize("model", LANGUAGE_MODELS, ids=lambda m: m.id)
def test_migration_language_rates_equal_catalog_rates(model):
    input_per_token, output_per_token = migration.LANGUAGE_RATES[model.id]
    assert Decimal(input_per_token) * 1_000_000 == Decimal(str(model.input_rate))
    assert Decimal(output_per_token) * 1_000_000 == Decimal(str(model.output_rate))


def test_every_language_model_and_operation_gets_a_row():
    # _upsert_language is called for model x LANGUAGE_OPERATIONS in upgrade(); check the inputs.
    for model in LANGUAGE_MODELS:
        assert model.id in migration.LANGUAGE_RATES
    assert len(migration.LANGUAGE_OPERATIONS) == len(set(migration.LANGUAGE_OPERATIONS))


def test_every_image_endpoint_has_a_migration_row():
    rows = _image_rows()
    for model in IMAGE_MODELS:
        assert (model.endpoint, model.kind) in rows, f"{model.key}: no row for {model.endpoint}"
        assert rows[(model.endpoint, model.kind)][0] == pytest.approx(model.base_price)
        if model.lora_endpoint:
            assert (model.lora_endpoint, model.kind) in rows, f"{model.key}: no LoRA row"
            assert rows[(model.lora_endpoint, model.kind)][0] == pytest.approx(model.lora_price)


def test_migration_has_no_unexpected_image_rows():
    expected = {(m.endpoint, m.kind) for m in IMAGE_MODELS}
    expected |= {(m.lora_endpoint, m.kind) for m in IMAGE_MODELS if m.lora_endpoint}
    assert set(_image_rows()) == expected


def test_removed_models_are_not_offered_and_are_deactivated():
    assert REMOVED_IMAGE_KEYS.isdisjoint(offered_keys("generate") + offered_keys("edit"))
    assert REMOVED_LANGUAGE_IDS.isdisjoint({m.id for m in LANGUAGE_MODELS})
    assert REMOVED_LANGUAGE_IDS == set(migration.REMOVED_FAL_LANGUAGE_MODELS)
    rows = _image_rows()
    for model, operation in migration.REMOVED_FAL_IMAGE_ROWS:
        assert (model, operation) not in rows, f"{model} is both seeded and deactivated"


def test_every_image_model_has_a_price():
    for model in IMAGE_MODELS:
        assert model.base_price > 0, model.key
        if model.supports_lora:
            assert model.lora_price and model.lora_price > 0, model.key
        if model.price_table:
            assert model.price_param in model.params, f"{model.key}: price_param is not a declared param"
            default = model.params[model.price_param]["default"]
            assert model.price_table[default] == pytest.approx(model.base_price), (
                f"{model.key}: base_price must equal the table price at the default option"
            )
            for option in model.params[model.price_param]["options"]:
                assert option in model.price_table, f"{model.key}: no price for {option}"


def test_each_catalog_has_exactly_one_default_per_kind():
    assert sum(m.is_default for m in LANGUAGE_MODELS) == 1
    for kind in ("generate", "edit"):
        assert sum(m.is_default for m in IMAGE_MODELS if m.kind == kind) == 1


@pytest.mark.parametrize("model", IMAGE_MODELS, ids=lambda m: f"{m.kind}:{m.key}")
def test_registry_resolves_catalog_endpoints(model):
    assert model_registry.resolve(model.key, model.kind) == ("fal", model.endpoint, model.kind)
    if model.lora_endpoint:
        assert model_registry.resolve(model.key, model.kind, with_lora=True) == (
            "fal", model.lora_endpoint, model.kind,
        )
    else:
        # No LoRA variant: with_lora falls back to the base entry.
        assert model_registry.resolve(model.key, model.kind, with_lora=True)[1] == model.endpoint


def test_registry_has_trainers_for_trainable_and_legacy_models():
    for model in IMAGE_MODELS:
        if model.trainable:
            assert model_registry.resolve(model.key, "train") == ("fal", model.trainer_endpoint, "train")
    for key, config in LEGACY_TRAINER_ENDPOINTS.items():
        assert model_registry.resolve(key, "train")[1] == config["training_endpoint"]


def test_registry_does_not_register_removed_models_for_generation_or_editing():
    for entry in model_registry.all_entries():
        if entry.operation in ("generate", "edit"):
            assert entry.short_name not in REMOVED_IMAGE_KEYS


def test_registry_strategy_keys_have_functions():
    strategies = __import__("app.services.pricing_engine", fromlist=["x"]).get_strategy_functions()
    for entry in model_registry.all_entries():
        if entry.pricing_strategy_key:
            assert entry.pricing_strategy_key in strategies


def test_curated_live_evidence_covers_every_offered_model():
    import json

    evidence = json.loads((Path(__file__).parents[2] / "docs" / "model-catalog-live-verification.json").read_text())
    rows = {(row["kind"], row["model"]): row for row in evidence["smoke"]}
    assert evidence["final_offered_counts"] == {"language": 17, "generate": 17, "edit": 17}
    for model in LANGUAGE_MODELS:
        for kind in ("text", "vision"):
            assert rows[kind, model.id]["ok"] and rows[kind, model.id]["offered"]
    for model in IMAGE_MODELS:
        assert rows[model.kind, model.key]["ok"] and rows[model.kind, model.key]["offered"]
