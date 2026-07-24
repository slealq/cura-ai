"""Unit tests for pure catalog cost calculations and token estimate routing."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.billing import CostCatalog
from app.services.cost_calculator import (
    calculate_cost,
    estimate_operation_tokens,
    estimate_sparks,
    get_catalog_entry,
    resolve_catalog_model,
)
from app.services.token_estimator import (
    estimate_embed_tokens,
    estimate_output_tokens,
    estimate_prompt_tokens,
    estimate_vision_input_tokens,
)


@pytest.fixture
def db():
    """Provide a fresh SQLite session containing only the cost catalog table."""
    engine = create_engine("sqlite:///:memory:")
    CostCatalog.metadata.create_all(engine, tables=[CostCatalog.__table__])
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def add_catalog_entry(db):
    """Insert a catalog row with defaults suitable for focused cost tests."""
    def add(**overrides):
        values = {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "operation": "tag",
            "cost_per_input_token": Decimal("0"),
            "cost_per_output_token": Decimal("0"),
            "cost_per_call": Decimal("0"),
            "platform_markup": Decimal("2.0"),
            "is_active": True,
        }
        values.update(overrides)
        entry = CostCatalog(**values)
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    return add


def test_get_catalog_entry_returns_exact_match(db, add_catalog_entry):
    entry = add_catalog_entry(model="gpt-4o")

    found, tier = get_catalog_entry(db, "openai", "gpt-4o", "tag")

    assert found.id == entry.id
    assert tier == "exact"


def test_get_catalog_entry_falls_back_to_wildcard(db, add_catalog_entry):
    entry = add_catalog_entry(model="*")

    found, tier = get_catalog_entry(db, "openai", "unlisted-model", "tag")

    assert found.id == entry.id
    assert tier == "wildcard"


def test_get_catalog_entry_falls_back_to_prefix_wildcard(db, add_catalog_entry):
    entry = add_catalog_entry(provider="openrouter", model="openrouter/*")

    found, tier = get_catalog_entry(db, "openrouter", "openrouter/grok-4-fast", "tag")

    assert found.id == entry.id
    assert tier == "prefix"


def test_get_catalog_entry_prioritizes_exact_then_wildcard_then_prefix(db, add_catalog_entry):
    prefix = add_catalog_entry(provider="openrouter", model="openrouter/*")
    wildcard = add_catalog_entry(provider="openrouter", model="*")
    exact = add_catalog_entry(provider="openrouter", model="openrouter/grok-4-fast")

    found, tier = get_catalog_entry(db, "openrouter", "openrouter/grok-4-fast", "tag")

    assert found.id == exact.id
    assert tier == "exact"

    found, tier = get_catalog_entry(db, "openrouter", "openrouter/other", "tag")

    assert found.id == wildcard.id
    assert tier == "wildcard"
    assert wildcard.id != prefix.id


def test_get_catalog_entry_returns_none_when_no_match_exists(db):
    assert get_catalog_entry(db, "openai", "missing", "tag") == (None, "none")


def test_get_catalog_entry_ignores_inactive_rows(db, add_catalog_entry):
    add_catalog_entry(model="gpt-4o", is_active=False)

    assert get_catalog_entry(db, "openai", "gpt-4o", "tag") == (None, "none")


def test_estimate_sparks_returns_zero_without_catalog_entry(db):
    assert estimate_sparks(db, "openai", "missing", "tag") == (Decimal("0"), None)


def test_estimate_sparks_uses_per_call_cost(db, add_catalog_entry):
    entry = add_catalog_entry(cost_per_call=Decimal("0.012345"), platform_markup=Decimal("1.5"))

    sparks, found = estimate_sparks(db, "openai", "gpt-4o-mini", "tag")

    assert sparks == Decimal("18.52")
    assert found.id == entry.id


def test_estimate_sparks_uses_token_costs(db, add_catalog_entry):
    entry = add_catalog_entry(
        cost_per_input_token=Decimal("0.0000015"),
        cost_per_output_token=Decimal("0.000004"),
        platform_markup=Decimal("2.0"),
    )

    sparks, found = estimate_sparks(
        db, "openai", "gpt-4o-mini", "tag", estimated_input_tokens=1000,
        estimated_output_tokens=250,
    )

    assert sparks == Decimal("5.00")
    assert found.id == entry.id


def test_estimate_sparks_uses_variable_pricing_engine(db, add_catalog_entry, monkeypatch):
    entry = add_catalog_entry(platform_markup=Decimal("1.7"))
    monkeypatch.setattr(
        "app.services.pricing_engine.compute_raw_cost",
        lambda provider, model, operation, params: Decimal("0.05"),
    )

    sparks, found = estimate_sparks(
        db, "openai", "gpt-4o-mini", "tag", generation_params={"size": "large"}
    )

    assert sparks == Decimal("85.00")
    assert found.id == entry.id


def test_estimate_sparks_falls_back_when_variable_pricing_is_unavailable(
    db, add_catalog_entry, monkeypatch
):
    add_catalog_entry(cost_per_call=Decimal("0.02"), platform_markup=Decimal("1.5"))
    monkeypatch.setattr(
        "app.services.pricing_engine.compute_raw_cost",
        lambda provider, model, operation, params: None,
    )

    sparks, _ = estimate_sparks(
        db, "openai", "gpt-4o-mini", "tag", generation_params={"size": "unknown"}
    )

    assert sparks == Decimal("30.00")


def test_calculate_cost_uses_provider_cost_and_catalog_markup(db, add_catalog_entry):
    entry = add_catalog_entry(platform_markup=Decimal("1.5"))

    raw, charged, detail = calculate_cost(
        db, "openai", "gpt-4o-mini", "tag", 10, 20, provider_cost=0.04
    )

    assert raw == Decimal("0.04")
    assert charged == Decimal("0.060")
    assert detail == {
        "cost_source": "provider",
        "provider_cost": 0.04,
        "platform_markup": 1.5,
        "sparks": 60.0,
        "catalog_entry_id": entry.id,
        "catalog_match_tier": "exact",
    }


def test_calculate_cost_uses_default_markup_for_provider_cost_catalog_miss(db):
    raw, charged, detail = calculate_cost(
        db, "openai", "missing", "tag", 10, 20, provider_cost=0.04
    )

    assert raw == Decimal("0.04")
    assert charged == Decimal("0.080")
    assert detail["cost_source"] == "provider"
    assert detail["platform_markup"] == 2.0
    assert detail["sparks"] == 80.0
    assert detail["catalog_entry_id"] is None
    assert detail["catalog_match_tier"] == "none"


def test_calculate_cost_uses_catalog_token_and_call_costs(db, add_catalog_entry):
    entry = add_catalog_entry(
        cost_per_input_token=Decimal("0.0000015"),
        cost_per_output_token=Decimal("0.000004"),
        cost_per_call=Decimal("0.01"),
        platform_markup=Decimal("2.0"),
    )

    raw, charged, detail = calculate_cost(db, "openai", "gpt-4o-mini", "tag", 1000, 250)

    assert raw == Decimal("0.012500000000")
    assert charged == Decimal("0.0250000000000")
    assert detail == {
        "cost_source": "catalog",
        "cost_per_input_token": 0.0000015,
        "cost_per_output_token": 0.000004,
        "cost_per_call": 0.01,
        "input_cost": 0.0015,
        "output_cost": 0.001,
        "call_cost": 0.01,
        "platform_markup": 2.0,
        "sparks": 25.0,
        "catalog_entry_id": entry.id,
        "catalog_match_tier": "exact",
    }


def test_calculate_cost_returns_zero_on_catalog_miss(db):
    assert calculate_cost(db, "openai", "missing", "tag", 1, 1) == (
        Decimal("0"), Decimal("0"), {"catalog_match_tier": "none"}
    )


def test_calculate_cost_only_applies_call_cost_for_none_tokens(db, add_catalog_entry):
    entry = add_catalog_entry(cost_per_call=Decimal("0.012"), platform_markup=Decimal("2.0"))

    raw, charged, detail = calculate_cost(db, "openai", "gpt-4o-mini", "tag", None, None)

    assert raw == Decimal("0.012000")
    assert charged == Decimal("0.0240000")
    assert detail["input_cost"] == 0.0
    assert detail["output_cost"] == 0.0
    assert detail["call_cost"] == 0.012
    assert detail["catalog_entry_id"] == entry.id


def test_resolve_catalog_model_leaves_full_model_names_unchanged(monkeypatch):
    def should_not_be_called(*args, **kwargs):
        raise AssertionError("registry should not be consulted for full model names")

    monkeypatch.setattr("app.services.model_registry.resolve", should_not_be_called)

    assert resolve_catalog_model("fal", "fal-ai/flux", "generate", with_lora=True) == (
        "fal", "fal-ai/flux", "generate"
    )


def test_resolve_catalog_model_uses_registry_for_short_names(monkeypatch):
    calls = []

    def resolve(model, operation, with_lora=False):
        calls.append((model, operation, with_lora))
        return "fal", "fal-ai/flux", "generate"

    monkeypatch.setattr("app.services.model_registry.resolve", resolve)

    assert resolve_catalog_model("original", "flux", "generate", with_lora=True) == (
        "fal", "fal-ai/flux", "generate"
    )
    assert calls == [("flux", "generate", True)]


def test_resolve_catalog_model_falls_back_on_registry_miss(monkeypatch):
    def missing(*args, **kwargs):
        raise KeyError("not registered")

    monkeypatch.setattr("app.services.model_registry.resolve", missing)

    assert resolve_catalog_model("fal", "unknown", "generate") == ("fal", "unknown", "generate")


@pytest.mark.parametrize("operation", ["tag", "describe"])
def test_estimate_operation_tokens_routes_vision_modes(operation):
    provider, model, width, height, prompt = "openai", "gpt-4o-mini", 640, 480, "describe this"

    result = estimate_operation_tokens(provider, model, operation, width, height, prompt)

    assert result == (
        estimate_vision_input_tokens(provider, model, width, height, prompt),
        estimate_output_tokens(model, operation),
    )


def test_estimate_operation_tokens_routes_evaluate_mode():
    provider, model, width, height, prompt = "openai", "gpt-4o-mini", 640, 480, "check quality"

    assert estimate_operation_tokens(provider, model, "evaluate", width, height, prompt) == (
        estimate_vision_input_tokens(provider, model, width, height, prompt),
        estimate_output_tokens(model, "custom"),
    )


def test_estimate_operation_tokens_routes_embed_mode():
    tags, description = ["a", "b"], "a description"

    assert estimate_operation_tokens(
        "openai", "gpt-4o-mini", "embed", tags=tags, description=description
    ) == (estimate_embed_tokens(tags, description), None)


@pytest.mark.parametrize("operation", ["summarize", "expand_prompt"])
def test_estimate_operation_tokens_routes_prompt_modes(operation):
    prompt = "A sufficiently specific prompt."

    assert estimate_operation_tokens("openai", "gpt-4o-mini", operation, prompt_text=prompt) == (
        estimate_prompt_tokens(prompt), 500
    )


@pytest.mark.parametrize("operation", ["generate", "train", "edit"])
def test_estimate_operation_tokens_returns_none_for_per_call_operations(operation):
    assert estimate_operation_tokens("openai", "gpt-4o-mini", operation) == (None, None)


def test_estimate_operation_tokens_defaults_vision_dimensions():
    provider, model, prompt = "openai", "gpt-4o-mini", "tag it"

    assert estimate_operation_tokens(provider, model, "tag", prompt_text=prompt) == (
        estimate_vision_input_tokens(provider, model, 1024, 1024, prompt),
        estimate_output_tokens(model, "tag"),
    )
