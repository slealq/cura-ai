"""Pydantic models and estimation logic for variable pricing rules.

.. deprecated::
    This module is superseded by :mod:`app.services.pricing_engine` which
    uses plain Python functions instead of JSON schemas.  No callers
    remain — kept for reference only.

The ``pricing_rules`` JSON column on ``CostCatalog`` stores one of
the rule types defined here.  ``estimate_from_rules()`` is the single
source of truth for cost estimation — used by both the preview API
and the billing orchestrator.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class FlatWithModifiersPricing(BaseModel):
    """Base $/image + resolution multipliers + optional surcharges."""

    pricing_type: Literal["flat_with_modifiers"]
    base_cost: float
    resolution_multipliers: dict[str, float] = {}
    default_resolution: str = "1K"
    surcharges: dict[str, float] = {}


class MegapixelPricing(BaseModel):
    """Per-megapixel pricing (first MP + extras)."""

    pricing_type: Literal["megapixel"]
    first_mp_cost: float
    extra_mp_cost: float
    default_width: int = 1024
    default_height: int = 1024


PricingRule = FlatWithModifiersPricing | MegapixelPricing


def estimate_from_rules(
    rules: dict | None,
    cost_per_call: Decimal | None,
    platform_markup: Decimal,
    params: dict | None = None,
) -> int:
    """Compute estimated sparks from pricing rules and generation parameters.

    Falls back to ``cost_per_call * markup * 1000`` when rules are absent
    or have an unknown type.

    Returns integer sparks.
    """
    params = params or {}

    if rules is None:
        # Legacy flat pricing
        raw = Decimal(str(cost_per_call or 0))
        return int(raw * platform_markup * 1000)

    pricing_type = rules.get("pricing_type")

    if pricing_type == "flat_with_modifiers":
        validated = FlatWithModifiersPricing(**rules)
        resolution = params.get("resolution", validated.default_resolution)
        multiplier = validated.resolution_multipliers.get(resolution, 1.0)
        surcharge_total = 0.0
        for key, amount in validated.surcharges.items():
            if params.get(f"enable_{key}") or params.get(key):
                surcharge_total += amount
        raw = Decimal(str(validated.base_cost * multiplier + surcharge_total))
        return int(raw * platform_markup * 1000)

    if pricing_type == "megapixel":
        validated = MegapixelPricing(**rules)
        width = params.get("width", validated.default_width)
        height = params.get("height", validated.default_height)
        total_mp = (width * height) / 1_000_000
        # fal.ai rounds to nearest megapixel (not ceiling):
        # 1024x1024 = 1.05 MP → 1 MP = $0.03
        # 1920x1080 = 2.07 MP → 2 MP = $0.045
        rounded_mp = max(1, round(total_mp))
        raw = Decimal(str(
            validated.first_mp_cost + max(0, rounded_mp - 1) * validated.extra_mp_cost
        ))
        return int(raw * platform_markup * 1000)

    # Unknown pricing_type — fall back to cost_per_call
    raw = Decimal(str(cost_per_call or 0))
    return int(raw * platform_markup * 1000)
