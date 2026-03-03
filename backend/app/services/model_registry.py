"""Unified model registry — single source of truth for all AI model metadata.

Every model the billing system needs to know about is registered here.
Adding a new model requires only adding a ``register()`` call below.

Public API:
    resolve()                  — map short name + operation → (provider, model, operation)
    get_pricing_strategy_key() — key into pricing_engine._STRATEGY_FUNCTIONS
    all_entries()              — iterate all registered models
    entries_for_operation()    — iterate models for a specific operation
    validate_against_catalog() — startup cross-check against CostCatalog
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelEntry:
    """Metadata for a single (model, operation) registration."""

    short_name: str
    """UI / API short name, e.g. "flux-dev", "qwen-image-max-edit"."""

    provider: str
    """Provider key for catalog lookup, e.g. "fal", "openai"."""

    catalog_model: str
    """Full model identifier in CostCatalog, e.g. "fal-ai/flux/dev"."""

    operation: str
    """Billing operation, e.g. "generate", "edit", "train"."""

    pricing_strategy_key: str | None = None
    """Key into pricing_engine._STRATEGY_FUNCTIONS for variable pricing."""

    lora_variant_of: str | None = None
    """If set, this is the with_lora variant of another short_name."""

    display_label: str | None = None
    """Optional UI display name."""

    supported_ops: frozenset[str] = field(default_factory=frozenset)
    """Extra supported operations (informational)."""


# ---------------------------------------------------------------------------
# Internal storage
# ---------------------------------------------------------------------------

# Keyed by (short_name, operation, is_lora_variant: bool)
_REGISTRY: dict[tuple[str, str, bool], ModelEntry] = {}

# For iteration by operation
_BY_OPERATION: dict[str, list[ModelEntry]] = {}


def register(entry: ModelEntry) -> None:
    """Register a model entry."""
    is_lora = entry.lora_variant_of is not None
    key = (entry.short_name, entry.operation, is_lora)
    if key in _REGISTRY:
        raise ValueError(f"Duplicate registration: {key}")
    _REGISTRY[key] = entry
    _BY_OPERATION.setdefault(entry.operation, []).append(entry)


# ---------------------------------------------------------------------------
# Public query API
# ---------------------------------------------------------------------------

def resolve(
    short_name: str,
    operation: str,
    with_lora: bool = False,
) -> tuple[str, str, str]:
    """Map a short model name + operation → (provider, catalog_model, operation).

    For generation models with LoRA variants, ``with_lora=True`` picks the
    LoRA-specific catalog entry.  Falls back to the non-LoRA entry.

    Raises ``KeyError`` if no match is found.
    """
    if with_lora:
        entry = _REGISTRY.get((short_name, operation, True))
        if entry:
            return entry.provider, entry.catalog_model, entry.operation

    entry = _REGISTRY.get((short_name, operation, False))
    if entry:
        return entry.provider, entry.catalog_model, entry.operation

    raise KeyError(f"No model registered for ({short_name!r}, {operation!r}, lora={with_lora})")


def get_pricing_strategy_key(
    provider: str,
    model: str,
    operation: str,
) -> str | None:
    """Return the pricing strategy key for a (provider, model, operation) triple.

    Scans all entries — matches on catalog_model (full name).
    Returns ``None`` if no entry has a pricing_strategy_key.
    """
    for entry in _REGISTRY.values():
        if (
            entry.provider == provider
            and entry.catalog_model == model
            and entry.operation == operation
            and entry.pricing_strategy_key is not None
        ):
            return entry.pricing_strategy_key
    return None


def all_entries() -> list[ModelEntry]:
    """Return all registered entries."""
    return list(_REGISTRY.values())


def entries_for_operation(operation: str) -> list[ModelEntry]:
    """Return entries for a specific operation (e.g. "generate", "edit", "train")."""
    return list(_BY_OPERATION.get(operation, []))


def generation_model_variants() -> dict[str, dict[str, tuple[str, str, str]]]:
    """Return generation models grouped by short_name with variant keys.

    Reproduces the shape of the old ``BillingService.GENERATION_MODEL_MAP``:
    ``{short_name: {"without_lora": (p, m, o), "with_lora": (p, m, o)}}``
    """
    result: dict[str, dict[str, tuple[str, str, str]]] = {}
    for entry in entries_for_operation("generate"):
        base = entry.lora_variant_of or entry.short_name
        variant_key = "with_lora" if entry.lora_variant_of else "without_lora"
        result.setdefault(base, {})[variant_key] = (
            entry.provider, entry.catalog_model, entry.operation,
        )
    return result


def flat_model_map(operation: str) -> dict[str, tuple[str, str, str]]:
    """Return a flat {short_name: (provider, catalog_model, operation)} map.

    Useful for edit and training models that have no LoRA variants.
    Only includes non-LoRA entries.
    """
    result: dict[str, tuple[str, str, str]] = {}
    for entry in entries_for_operation(operation):
        if entry.lora_variant_of is None:
            result[entry.short_name] = (
                entry.provider, entry.catalog_model, entry.operation,
            )
    return result


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_against_catalog(db) -> list[str]:
    """Cross-check every registered model against CostCatalog rows.

    Returns a list of error/warning strings (empty = all good).
    Does NOT raise — callers should log and optionally report to Sentry.
    """
    from app.services.cost_calculator import get_catalog_entry

    errors: list[str] = []

    for entry in _REGISTRY.values():
        cat, tier = get_catalog_entry(db, entry.provider, entry.catalog_model, entry.operation)
        if cat is None:
            errors.append(
                f"MISSING catalog entry: {entry.provider}/{entry.catalog_model} "
                f"op={entry.operation} (short_name={entry.short_name})"
            )
        elif cat.platform_markup is not None:
            markup = float(cat.platform_markup)
            if markup < 0.5 or markup > 10.0:
                errors.append(
                    f"SUSPECT markup {markup}x on {entry.provider}/{entry.catalog_model} "
                    f"op={entry.operation}"
                )

    # Check pricing strategy keys have matching functions
    from app.services.pricing_engine import get_strategy_functions

    strategy_fns = get_strategy_functions()
    for entry in _REGISTRY.values():
        if entry.pricing_strategy_key and entry.pricing_strategy_key not in strategy_fns:
            errors.append(
                f"MISSING pricing function for strategy_key={entry.pricing_strategy_key!r} "
                f"(model={entry.short_name})"
            )

    return errors


# ---------------------------------------------------------------------------
# Model registrations — THE single source of truth
# ---------------------------------------------------------------------------

# --- Generation models (5 base + 2 LoRA variants) ---

register(ModelEntry(
    short_name="flux-dev",
    provider="fal",
    catalog_model="fal-ai/flux/dev",
    operation="generate",
))

register(ModelEntry(
    short_name="flux-dev",
    provider="fal",
    catalog_model="fal-ai/flux-lora",
    operation="generate",
    lora_variant_of="flux-dev",
))

register(ModelEntry(
    short_name="qwen-2.5",
    provider="fal",
    catalog_model="fal-ai/qwen-image-2512",
    operation="generate",
))

register(ModelEntry(
    short_name="qwen-2.5",
    provider="fal",
    catalog_model="fal-ai/qwen-image-2512/lora",
    operation="generate",
    lora_variant_of="qwen-2.5",
))

register(ModelEntry(
    short_name="nano-banana-pro",
    provider="fal",
    catalog_model="fal-ai/nano-banana-pro",
    operation="generate",
    pricing_strategy_key="nano_banana_pro",
))

register(ModelEntry(
    short_name="nano-banana-2",
    provider="fal",
    catalog_model="fal-ai/nano-banana-2",
    operation="generate",
    pricing_strategy_key="nano_banana_2",
))

register(ModelEntry(
    short_name="flux-2-pro",
    provider="fal",
    catalog_model="fal-ai/flux-2-pro",
    operation="generate",
    pricing_strategy_key="flux_2_pro_mp",
))

# --- Edit models (6) ---

register(ModelEntry(
    short_name="qwen-image-max-edit",
    provider="fal",
    catalog_model="fal-ai/qwen-image-max/edit",
    operation="edit",
))

register(ModelEntry(
    short_name="kling-image",
    provider="fal",
    catalog_model="fal-ai/kling-image/o3/image-to-image",
    operation="edit",
))

register(ModelEntry(
    short_name="wan-25",
    provider="fal",
    catalog_model="fal-ai/wan-25-preview/image-to-image",
    operation="edit",
))

register(ModelEntry(
    short_name="grok-imagine",
    provider="fal",
    catalog_model="xai/grok-imagine-image/edit",
    operation="edit",
))

register(ModelEntry(
    short_name="face-swap",
    provider="fal",
    catalog_model="half-moon-ai/ai-face-swap/faceswapimage",
    operation="edit",
))

register(ModelEntry(
    short_name="nano-banana-pro-edit",
    provider="fal",
    catalog_model="fal-ai/nano-banana-pro/edit",
    operation="edit",
    pricing_strategy_key="nano_banana_pro_edit",
))

# --- Training models (2) ---

register(ModelEntry(
    short_name="flux-dev",
    provider="fal",
    catalog_model="fal-ai/flux-lora-fast-training",
    operation="train",
))

register(ModelEntry(
    short_name="qwen-2.5",
    provider="fal",
    catalog_model="fal-ai/qwen-image-2512-trainer-v2",
    operation="train",
))
