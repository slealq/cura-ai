"""Python-based pricing engine for variable-cost generation models.

Instead of storing pricing formulas as JSON in the database, each
(provider, model, operation) triple maps to a plain Python function
that receives the full request parameters and returns raw USD cost.

``compute_raw_cost()`` is the single entry point — it returns ``None``
when no function is registered, signalling callers to fall back to the
flat catalog rate.
"""
from __future__ import annotations

from decimal import Decimal

# ---------------------------------------------------------------------------
# Image-size preset → (width, height) for flux-2-pro
# ---------------------------------------------------------------------------
IMAGE_SIZE_DIMS: dict[str, tuple[int, int]] = {
    "square_hd": (1024, 1024),
    "square": (512, 512),
    "landscape_4_3": (1024, 768),
    "landscape_16_9": (1344, 768),
    "portrait_4_3": (768, 1024),
    "portrait_16_9": (768, 1344),
}

# ---------------------------------------------------------------------------
# Resolution multipliers for nano-banana models
# ---------------------------------------------------------------------------
_NANO_RESOLUTION_MULTIPLIERS: dict[str, float] = {
    "0.5K": 0.75,
    "1K": 1.0,
    "2K": 1.5,
    "4K": 2.0,
}

_WEB_SEARCH_SURCHARGE = Decimal("0.015")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_dimensions(params: dict) -> tuple[int, int]:
    """Resolve image dimensions from params.

    Checks ``image_size`` preset string first, then explicit
    ``width``/``height``, defaulting to 1024×1024.
    """
    image_size = params.get("image_size")
    if image_size and image_size in IMAGE_SIZE_DIMS:
        return IMAGE_SIZE_DIMS[image_size]
    w = params.get("width", 1024)
    h = params.get("height", 1024)
    return int(w), int(h)


# ---------------------------------------------------------------------------
# Pricing functions — each returns raw USD (before markup)
# ---------------------------------------------------------------------------

def _flux_2_pro_generate(params: dict) -> Decimal:
    """$0.03 for the first megapixel + $0.015 per extra MP."""
    w, h = _resolve_dimensions(params)
    total_mp = (w * h) / 1_000_000
    rounded_mp = max(1, round(total_mp))
    raw = Decimal("0.03") + Decimal("0.015") * max(0, rounded_mp - 1)
    return raw


def _nano_banana_pro_generate(params: dict) -> Decimal:
    """$0.15 × resolution_mult + optional web_search surcharge."""
    resolution = params.get("resolution", "1K")
    multiplier = Decimal(str(_NANO_RESOLUTION_MULTIPLIERS.get(resolution, 1.0)))
    raw = Decimal("0.15") * multiplier
    if params.get("enable_web_search") or params.get("web_search"):
        raw += _WEB_SEARCH_SURCHARGE
    return raw


def _nano_banana_2_generate(params: dict) -> Decimal:
    """$0.08 × resolution_mult + optional web_search surcharge."""
    resolution = params.get("resolution", "1K")
    multiplier = Decimal(str(_NANO_RESOLUTION_MULTIPLIERS.get(resolution, 1.0)))
    raw = Decimal("0.08") * multiplier
    if params.get("enable_web_search") or params.get("web_search"):
        raw += _WEB_SEARCH_SURCHARGE
    return raw


# ---------------------------------------------------------------------------
# Strategy functions keyed by strategy name (set in model_registry)
# ---------------------------------------------------------------------------

_STRATEGY_FUNCTIONS: dict[str, callable] = {
    "flux_2_pro_mp": _flux_2_pro_generate,
    "nano_banana_pro": _nano_banana_pro_generate,
    "nano_banana_pro_edit": _nano_banana_pro_generate,  # same formula
    "nano_banana_2": _nano_banana_2_generate,
}


def get_strategy_functions() -> dict[str, callable]:
    """Return the strategy function dict — used by model_registry validation."""
    return _STRATEGY_FUNCTIONS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_raw_cost(
    provider: str,
    model: str,
    operation: str,
    params: dict,
) -> Decimal | None:
    """Compute raw USD cost using a registered pricing function.

    Looks up the pricing strategy key via the model registry, then
    dispatches to the matching function.  Returns ``None`` when no
    function is registered — callers should fall back to the flat
    catalog rate.
    """
    from app.services.model_registry import get_pricing_strategy_key

    key = get_pricing_strategy_key(provider, model, operation)
    if key is None:
        return None
    fn = _STRATEGY_FUNCTIONS.get(key)
    if fn is None:
        return None
    return fn(params)


def has_variable_pricing(provider: str, model: str, operation: str) -> bool:
    """Return True if the model has a registered pricing function.

    Used by the frontend to decide which models need dynamic estimates.
    """
    from app.services.model_registry import get_pricing_strategy_key

    key = get_pricing_strategy_key(provider, model, operation)
    return key is not None and key in _STRATEGY_FUNCTIONS
