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
# Registry
# ---------------------------------------------------------------------------

# Key: (provider, model, operation) → pricing function
_PRICING_REGISTRY: dict[tuple[str, str, str], callable] = {
    ("fal", "fal-ai/flux-2-pro", "generate"): _flux_2_pro_generate,
    ("fal", "fal-ai/nano-banana-pro", "generate"): _nano_banana_pro_generate,
    ("fal", "fal-ai/nano-banana-pro/edit", "edit"): _nano_banana_pro_generate,
    ("fal", "fal-ai/nano-banana-2", "generate"): _nano_banana_2_generate,
}


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

    Returns ``None`` when no function is registered — callers should
    fall back to the flat catalog rate.
    """
    fn = _PRICING_REGISTRY.get((provider, model, operation))
    if fn is None:
        return None
    return fn(params)


def has_variable_pricing(provider: str, model: str, operation: str) -> bool:
    """Return True if the model has a registered pricing function.

    Used by the frontend to decide which models need dynamic estimates.
    """
    return (provider, model, operation) in _PRICING_REGISTRY
