"""Pure cost calculation functions extracted from BillingService."""
import logging
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.billing import CostCatalog

logger = logging.getLogger(__name__)

# Balance is denominated in sparks; cost catalog prices are in USD.
# 1 spark = $0.001, so multiply USD by 1000 to get sparks.
USD_TO_SPARKS = Decimal("1000")


def get_catalog_entry(
    db: Session, provider: str, model: str, operation: str
) -> tuple[CostCatalog | None, str]:
    """Catalog lookup with fallback: exact match -> wildcard model -> prefix -> None.

    Returns (entry, match_tier) where match_tier is one of:
    "exact", "wildcard", "prefix", or "none".
    """
    # Exact match first
    entry = (
        db.query(CostCatalog)
        .filter(
            CostCatalog.provider == provider,
            CostCatalog.model == model,
            CostCatalog.operation == operation,
            CostCatalog.is_active.is_(True),
        )
        .first()
    )
    if entry:
        return entry, "exact"

    # Wildcard model fallback (e.g., fal/* for generate)
    entry = (
        db.query(CostCatalog)
        .filter(
            CostCatalog.provider == provider,
            CostCatalog.model == "*",
            CostCatalog.operation == operation,
            CostCatalog.is_active.is_(True),
        )
        .first()
    )
    if entry:
        return entry, "wildcard"

    # Partial wildcard (e.g., "openrouter/*" matches "openrouter/qwen...")
    wildcards = (
        db.query(CostCatalog)
        .filter(
            CostCatalog.provider == provider,
            CostCatalog.model.like("%*%"),
            CostCatalog.operation == operation,
            CostCatalog.is_active.is_(True),
        )
        .all()
    )
    # Sort by prefix length descending so longest (most specific) prefix wins
    wildcards.sort(key=lambda wc: len(wc.model.replace("*", "")), reverse=True)
    for wc in wildcards:
        prefix = wc.model.replace("*", "")
        if model.startswith(prefix):
            return wc, "prefix"

    return None, "none"


def estimate_sparks(
    db: Session,
    provider: str,
    model: str,
    operation: str,
    estimated_input_tokens: int | None = None,
    estimated_output_tokens: int | None = None,
) -> tuple[int, CostCatalog | None]:
    """Estimate cost in integer sparks. Used by all estimate endpoints.

    Returns (sparks, catalog_entry).
    """
    entry, _ = get_catalog_entry(db, provider, model, operation)
    if not entry:
        return 0, None

    raw = Decimal("0")
    if entry.cost_per_call and entry.cost_per_call > 0:
        raw += entry.cost_per_call
    if estimated_input_tokens and entry.cost_per_input_token:
        raw += entry.cost_per_input_token * estimated_input_tokens
    if estimated_output_tokens and entry.cost_per_output_token:
        raw += entry.cost_per_output_token * estimated_output_tokens

    charged = raw * entry.platform_markup
    sparks = int(charged * USD_TO_SPARKS)
    return sparks, entry


def calculate_cost(
    db: Session,
    provider: str,
    model: str,
    operation: str,
    input_tokens: int | None,
    output_tokens: int | None,
    provider_cost: float | None = None,
    user_email: str | None = None,
) -> tuple[Decimal, Decimal, dict | None]:
    """Calculate raw and charged cost from catalog or provider-reported cost.

    If provider_cost is given, use it as raw_cost and apply only
    platform_markup from the catalog (default 2.0x if no entry).
    Otherwise, compute from per-token/per-call catalog rates.

    Returns (raw_cost, charged_cost, detail).
    Does NOT record BillingAnomaly on catalog miss — that is the caller's
    responsibility (BillingService handles it).
    """
    entry, match_tier = get_catalog_entry(db, provider, model, operation)

    # --- Provider-reported cost path (e.g. fal.ai) ---
    if provider_cost is not None:
        raw_cost = Decimal(str(provider_cost))
        markup = entry.platform_markup if entry else Decimal("2.0")
        charged_cost = raw_cost * markup
        sparks = charged_cost * USD_TO_SPARKS

        logger.info(
            "BILLING | user=%s %s/%s op=%s "
            "in_tok=%s out_tok=%s "
            "provider_cost=$%.8f markup=%.1fx "
            "charged=$%.8f sparks=%.2f (source=provider)",
            user_email or "?", provider, model, operation,
            input_tokens, output_tokens,
            float(raw_cost), float(markup),
            float(charged_cost), float(sparks),
        )

        detail = {
            "cost_source": "provider",
            "provider_cost": float(raw_cost),
            "platform_markup": float(markup),
            "sparks": float(sparks),
            "catalog_entry_id": entry.id if entry else None,
            "catalog_match_tier": match_tier,
        }
        return raw_cost, charged_cost, detail

    # --- Catalog-based cost path ---
    if not entry:
        logger.warning(
            "BILLING MISS | user=%s provider=%s model=%s op=%s "
            "in_tok=%s out_tok=%s — no catalog entry, charging 0",
            user_email or "?", provider, model, operation,
            input_tokens, output_tokens,
        )
        return Decimal("0"), Decimal("0"), {"catalog_match_tier": "none"}

    input_cost = Decimal("0")
    output_cost = Decimal("0")
    call_cost = Decimal("0")

    if entry.cost_per_call and entry.cost_per_call > 0:
        call_cost = entry.cost_per_call
    if input_tokens and entry.cost_per_input_token:
        input_cost = entry.cost_per_input_token * input_tokens
    if output_tokens and entry.cost_per_output_token:
        output_cost = entry.cost_per_output_token * output_tokens

    raw_cost = input_cost + output_cost + call_cost
    charged_cost = raw_cost * entry.platform_markup
    sparks = charged_cost * USD_TO_SPARKS

    logger.info(
        "BILLING | user=%s %s/%s op=%s "
        "in_tok=%s out_tok=%s "
        "rates(in=%.10f out=%.10f call=%.6f) "
        "raw($%.8f = in:$%.8f + out:$%.8f + call:$%.8f) "
        "markup=%.1fx charged=$%.8f sparks=%.2f",
        user_email or "?", provider, model, operation,
        input_tokens, output_tokens,
        float(entry.cost_per_input_token or 0),
        float(entry.cost_per_output_token or 0),
        float(entry.cost_per_call or 0),
        float(raw_cost), float(input_cost), float(output_cost), float(call_cost),
        float(entry.platform_markup),
        float(charged_cost), float(sparks),
    )

    detail = {
        "cost_source": "catalog",
        "cost_per_input_token": float(entry.cost_per_input_token or 0),
        "cost_per_output_token": float(entry.cost_per_output_token or 0),
        "cost_per_call": float(entry.cost_per_call or 0),
        "input_cost": float(input_cost),
        "output_cost": float(output_cost),
        "call_cost": float(call_cost),
        "platform_markup": float(entry.platform_markup),
        "sparks": float(sparks),
        "catalog_entry_id": entry.id,
        "catalog_match_tier": match_tier,
    }

    return raw_cost, charged_cost, detail
