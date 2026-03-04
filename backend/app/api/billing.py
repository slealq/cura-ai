"""Billing API endpoints for user balance, usage, and admin cost management."""
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.settings import (
    CURATED_OPENAI_VISION_MODELS,
    _get_anthropic_models,
    _get_fal_models,
)
from app.core.security import get_current_user, require_admin
from app.db.base import get_db
from app.models.billing import BillingAnomaly, CostCatalog, UsageRecord
from app.models.user import User
from app.services.billing_service import BillingService
from app.services.cost_calculator import estimate_sparks as _estimate_sparks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# --- Pydantic schemas ---

class BalanceResponse(BaseModel):
    balance: float
    reserved: float
    available: float
    currency: str


class TransactionResponse(BaseModel):
    id: int
    amount: float
    transaction_type: str
    description: str
    reference_id: int | None
    created_by: int | None
    created_at: str


class TransactionListResponse(BaseModel):
    items: list[TransactionResponse]
    total: int


class OperationUsageDetail(BaseModel):
    operation: str
    count: int
    total_sparks: float
    avg_sparks: float


class UsageSummaryResponse(BaseModel):
    total_cost: float
    by_operation: dict[str, float]
    by_provider: dict[str, float]
    record_count: int
    by_operation_detail: list[OperationUsageDetail] = []


class AddCreditsRequest(BaseModel):
    amount: float
    description: str


class CatalogEntryRequest(BaseModel):
    provider: str
    model: str
    operation: str
    cost_per_input_token: float | None = 0
    cost_per_output_token: float | None = 0
    cost_per_call: float | None = 0
    platform_markup: float = 2.0
    pricing_rules: dict | None = None


class OperationMarkup(BaseModel):
    operation: str
    platform_markup: float


class ModelBulkUpdateRequest(BaseModel):
    provider: str
    model: str
    cost_per_input_token: float | None = 0
    cost_per_output_token: float | None = 0
    cost_per_call: float | None = 0
    operations: list[OperationMarkup]


class CatalogEntryResponse(BaseModel):
    id: int
    provider: str
    model: str
    operation: str
    cost_per_input_token: float | None
    cost_per_output_token: float | None
    cost_per_call: float | None
    platform_markup: float
    pricing_rules: dict | None = None
    is_active: bool
    created_at: str
    updated_at: str


class AdminUserBalance(BaseModel):
    user_id: int
    email: str
    display_name: str | None
    balance: float
    total_spent: float
    last_activity: str | None


class PlatformSummaryResponse(BaseModel):
    total_raw_cost: float
    total_charged: float
    margin: float
    by_provider: dict[str, float]
    by_operation: dict[str, float]
    record_count: int


class GenerationCostsResponse(BaseModel):
    """Per-image generation cost in sparks for each base model."""
    costs: dict[str, dict[str, float]]
    expand_prompt_cost: float
    variable_pricing_models: list[str] = []


class GenerationEstimateRequest(BaseModel):
    """Request body for dynamic generation cost estimate."""
    base_model: str
    resolution: str | None = None
    enable_web_search: bool = False
    width: int | None = None
    height: int | None = None
    image_size: str | None = None
    with_lora: bool = False


class GenerationEstimateResponse(BaseModel):
    """Response for dynamic generation cost estimate."""
    estimated_sparks: float
    base_model: str


class BillingLogEntryResponse(BaseModel):
    id: int
    user_id: int
    user_email: str
    user_display_name: str | None
    pipeline_log_id: int | None
    operation: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    raw_cost: float
    charged_cost: float
    detail: dict | None
    created_at: str


class BillingLogListResponse(BaseModel):
    items: list[BillingLogEntryResponse]
    total: int
    skip: int
    limit: int


# --- Reconciliation / Anomalies / Metrics schemas ---


class ReconciliationRow(BaseModel):
    operation: str
    provider: str
    model: str
    total_decisions: int
    avg_estimated_sparks: float
    avg_actual_sparks: float
    avg_delta: float
    avg_delta_pct: float
    min_delta: float
    max_delta: float
    total_estimated: int
    total_actual: int


class ReconciliationResponse(BaseModel):
    items: list[ReconciliationRow]
    threshold_pct: float
    threshold_violations: int


class AnomalyResponse(BaseModel):
    id: int
    user_id: int | None
    anomaly_type: str
    provider: str | None
    model: str | None
    operation: str | None
    detail: dict | None
    resolved: bool
    created_at: str


class AnomalyListResponse(BaseModel):
    items: list[AnomalyResponse]
    total: int
    skip: int
    limit: int


class AnomalyGroupSummary(BaseModel):
    anomaly_type: str
    provider: str | None
    model: str | None
    operation: str | None
    count: int


class AnomalySummaryResponse(BaseModel):
    groups: list[AnomalyGroupSummary]
    total_unresolved: int
    last_24h_count: int


class OperationMetric(BaseModel):
    operation: str
    count: int
    avg_sparks: float
    failure_count: int


class ProviderMetric(BaseModel):
    provider: str
    count: int
    avg_sparks: float
    failure_count: int


class MetricAlert(BaseModel):
    level: str
    message: str


class MetricsResponse(BaseModel):
    hours: int
    total_operations: int
    ops_per_hour: float
    failure_rate: float
    cancel_rate: float
    pending_decisions: int
    avg_delta_pct: float
    catalog_miss_count: int
    anomalies_by_type: dict[str, int] = {}
    by_operation: list[OperationMetric]
    by_provider: list[ProviderMetric]
    alerts: list[MetricAlert]


class ScatterPoint(BaseModel):
    estimated_sparks: float
    actual_sparks: int
    operation: str
    provider: str
    created_at: str


class ScatterResponse(BaseModel):
    items: list[ScatterPoint]


class TrendBucket(BaseModel):
    hour: str
    total: int
    by_type: dict[str, int]


class TrendResponse(BaseModel):
    items: list[TrendBucket]
    hours: int


class EvaluationCostBreakdown(BaseModel):
    generate_per_image: float
    describe_per_image: float
    embed_per_image: float
    vision_eval_per_image: float
    creative_prompts: float
    assessment: float
    per_reference_pair: float
    per_creative_pair: float


class EvaluationCostTotals(BaseModel):
    reference: float
    creative: float
    overhead: float
    total: float


class EvaluationCostParams(BaseModel):
    base_model: str
    sample_count: int
    creative_count: int


class EvaluationCostProviders(BaseModel):
    generation: str
    vision: str
    evaluation: str
    embedding: str


class EvaluationCostsResponse(BaseModel):
    breakdown: EvaluationCostBreakdown
    totals: EvaluationCostTotals
    params: EvaluationCostParams
    providers: EvaluationCostProviders


class SummarizeCostsResponse(BaseModel):
    per_cluster: float
    cluster_count: int
    total: float
    provider: str
    estimated_input_tokens: int
    estimated_output_tokens: int


# --- User endpoints ---

@router.get("/balance", response_model=BalanceResponse)
def get_balance(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = BillingService(db, current_user.id)
    balance = svc.get_balance()
    reserved = svc.get_reserved()
    return {
        "balance": balance,
        "reserved": reserved,
        "available": balance - reserved,
        "currency": "credits",
    }


@router.get("/transactions", response_model=TransactionListResponse)
def get_transactions(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = BillingService(db, current_user.id)
    items, total = svc.get_transaction_history(limit=limit, skip=skip)
    return {
        "items": [
            {
                "id": t.id,
                "amount": t.amount_sparks,
                "transaction_type": t.transaction_type.value,
                "description": t.description,
                "reference_id": t.reference_id,
                "created_by": t.created_by,
                "created_at": t.created_at.isoformat(),
            }
            for t in items
        ],
        "total": total,
    }


@router.get("/usage", response_model=UsageSummaryResponse)
def get_usage(
    start_date: str | None = None,
    end_date: str | None = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    svc = BillingService(db, current_user.id)
    return svc.get_usage_summary(start_date=start, end_date=end)


@router.get("/generation-costs", response_model=GenerationCostsResponse)
def get_generation_costs(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get per-image generation cost in sparks for each base model."""
    from app.services.token_estimator import estimate_prompt_tokens

    # Estimate expand_prompt cost using estimate_sparks()
    input_tokens = estimate_prompt_tokens("Expand this prompt into a detailed description")
    db_avg_out = BillingService.get_average_output_tokens(
        db, "openai", "gpt-4o-mini", "expand_prompt",
    )
    output_tokens = db_avg_out if db_avg_out is not None else 200
    expand_sparks, _ = _estimate_sparks(
        db, "openai", "gpt-4o-mini", "expand_prompt",
        estimated_input_tokens=input_tokens,
        estimated_output_tokens=output_tokens,
    )
    from app.services.model_registry import generation_model_variants
    from app.services.pricing_engine import has_variable_pricing

    costs = BillingService.get_generation_costs(db)

    # Compute which base models have variable pricing
    variable_models: list[str] = []
    for base_model, variants in generation_model_variants().items():
        for _variant_key, (prov, mod, op) in variants.items():
            if has_variable_pricing(prov, mod, op):
                variable_models.append(base_model)
                break

    return {
        "costs": costs,
        "expand_prompt_cost": expand_sparks,
        "variable_pricing_models": variable_models,
    }


@router.post("/generation-estimate", response_model=GenerationEstimateResponse)
def estimate_generation_cost(
    body: GenerationEstimateRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Dynamic cost estimate for generation with specific parameters."""
    from app.services.cost_calculator import resolve_catalog_model

    # Resolve short model name to catalog triple
    provider, model, operation = resolve_catalog_model(
        "fal", body.base_model, "generate", with_lora=body.with_lora,
    )

    # Build params dict for pricing engine
    gen_params: dict = {}
    if body.resolution:
        gen_params["resolution"] = body.resolution
    if body.enable_web_search:
        gen_params["enable_web_search"] = True
    if body.width:
        gen_params["width"] = body.width
    if body.height:
        gen_params["height"] = body.height
    if body.image_size:
        gen_params["image_size"] = body.image_size

    sparks, _ = _estimate_sparks(
        db, provider, model, operation,
        generation_params=gen_params,
    )
    return {"estimated_sparks": sparks, "base_model": body.base_model}


class EditCostsResponse(BaseModel):
    """Per-call edit cost in sparks by edit model."""
    costs: dict[str, float]


class TrainingCostsResponse(BaseModel):
    """Per-job training cost in sparks by base model."""
    costs: dict[str, float]


@router.get("/edit-costs", response_model=EditCostsResponse)
def get_edit_costs(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get per-call edit cost in sparks for each edit model."""
    return {"costs": BillingService.get_edit_costs(db)}


@router.get("/training-costs", response_model=TrainingCostsResponse)
def get_training_costs(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get per-job training cost in sparks for each base model."""
    return {"costs": BillingService.get_training_costs(db)}


class EstimationBasis(BaseModel):
    width: int
    height: int
    source: str  # "provided" | "folder_avg" | "default"


class VisionCostsResponse(BaseModel):
    """Estimated per-call vision cost in sparks by provider → model → mode."""
    costs: dict[str, dict[str, dict[str, float]]]
    estimation_basis: EstimationBasis | None = None


class VisionCostEstimateRequest(BaseModel):
    width: int | None = None
    height: int | None = None
    folder_id: int | None = None


# Map provider → (catalog_provider, list of vision model IDs)
# Curated lists imported from app.api.settings at top of file.
_VISION_PROVIDER_MODELS = {
    "openai": ("openai", [m.id for m in CURATED_OPENAI_VISION_MODELS]),
    "anthropic": ("anthropic", [m.id for m in _get_anthropic_models()]),
    "fal": ("fal", [m.id for m in _get_fal_models() if "vision" in m.capabilities]),
}


def _compute_vision_costs(
    db: Session,
    user_id: int,
    width: int = 1024,
    height: int = 1024,
) -> dict[str, dict[str, dict[str, float]]]:
    """Shared logic: compute vision cost estimates using formula-based token estimation.

    Input tokens are always computed from image dimensions + current prompt text.
    Output tokens use DEFAULT_OUTPUT_TOKENS per mode.
    This ensures estimates always reflect the user's current prompt settings.
    """
    from app.services.settings_service import SettingsService
    from app.services.token_estimator import (
        estimate_embed_tokens,
        estimate_image_tokens,
        estimate_output_tokens,
        estimate_prompt_tokens,
    )

    # Get user's active composed prompt text
    settings_svc = SettingsService(db, user_id)
    tag_prompt_text = settings_svc.get_tag_prompt()
    desc_prompt_text = settings_svc.get_description_prompt()

    # Embed cost (always OpenAI text-embedding-3-small)
    embed_tokens = estimate_embed_tokens()
    embed_cost_sparks_dec, _ = _estimate_sparks(
        db, "openai", "text-embedding-3-small", "embed",
        estimated_input_tokens=embed_tokens,
    )
    embed_cost_sparks = float(embed_cost_sparks_dec)

    result: dict[str, dict[str, dict[str, float]]] = {}

    for provider_key, (cat_provider, model_ids) in _VISION_PROVIDER_MODELS.items():
        provider_costs: dict[str, dict[str, float]] = {}
        for model_id in model_ids:
            costs: dict[str, float] = {}
            for mode in ("tag", "describe", "custom"):
                # "custom" mode uses the describer provider, so map to "describe"
                # for catalog lookup. Custom operations have similar token
                # profiles to describe operations.
                operation = "tag" if mode == "tag" else "describe"
                prompt_text = tag_prompt_text if mode == "tag" else desc_prompt_text

                img_tokens = estimate_image_tokens(
                    cat_provider, model_id, width, height,
                )
                prompt_tokens = estimate_prompt_tokens(prompt_text)
                input_tokens = img_tokens + prompt_tokens
                output_tokens = estimate_output_tokens(model_id, mode)

                sparks_est, entry = _estimate_sparks(
                    db, cat_provider, model_id, operation,
                    estimated_input_tokens=input_tokens,
                    estimated_output_tokens=output_tokens,
                )
                costs[mode] = float(sparks_est)
                if entry:
                    logger.info(
                        "ESTIMATE | %s/%s %s %dx%d | "
                        "img_tok=%d + prompt_tok=%d(%dchars) = in=%d | "
                        "out=%d | sparks=%.2f",
                        cat_provider, model_id, mode, width, height,
                        img_tokens, prompt_tokens, len(prompt_text), input_tokens,
                        output_tokens, float(sparks_est),
                    )

            costs["embed"] = embed_cost_sparks
            costs["total"] = round(
                costs.get("tag", 0) + costs.get("describe", 0) + embed_cost_sparks, 1
            )
            provider_costs[model_id] = costs
        result[provider_key] = provider_costs

    return result


@router.get("/vision-costs", response_model=VisionCostsResponse)
def get_vision_costs(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get estimated per-call vision cost in sparks (default 1024x1024 dimensions)."""
    costs = _compute_vision_costs(db, current_user.id)
    return {
        "costs": costs,
        "estimation_basis": {"width": 1024, "height": 1024, "source": "default"},
    }


@router.post("/vision-costs", response_model=VisionCostsResponse)
def estimate_vision_costs(
    body: VisionCostEstimateRequest,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get estimated per-call vision cost using actual image dimensions.

    Accepts explicit width/height, or a folder_id to compute avg dims server-side.
    Falls back to 1024x1024 when neither is provided.
    """
    width, height, source = 1024, 1024, "default"

    if body.width is not None and body.height is not None:
        width, height, source = body.width, body.height, "provided"
    elif body.folder_id is not None:
        from app.services.folder_service import FolderService
        folder_svc = FolderService(db, current_user.id)
        stats = folder_svc.get_folder_dimension_stats(body.folder_id)
        if stats["count"] > 0:
            width, height, source = stats["avg_width"], stats["avg_height"], "folder_avg"

    costs = _compute_vision_costs(db, current_user.id, width, height)
    return {
        "costs": costs,
        "estimation_basis": {"width": width, "height": height, "source": source},
    }


@router.get("/evaluation-costs", response_model=EvaluationCostsResponse)
def get_evaluation_costs(
    base_model: str = Query("flux-dev"),
    sample_count: int = Query(5, ge=1, le=50),
    creative_count: int = Query(0, ge=0, le=20),
    vision_eval_provider: str | None = None,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Estimate evaluation costs broken down by sub-operation."""
    return BillingService.get_evaluation_costs(
        db, current_user.id,
        base_model=base_model,
        sample_count=sample_count,
        creative_count=creative_count,
        vision_eval_provider=vision_eval_provider,
    )


@router.get("/summarize-costs", response_model=SummarizeCostsResponse)
def get_summarize_costs(
    cluster_count: int = Query(1, ge=1, le=500),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Estimate cluster summarization costs."""
    return BillingService.get_summarize_costs(db, current_user.id, cluster_count)


# --- Admin endpoints ---

@router.get("/admin/users", response_model=list[AdminUserBalance])
def admin_get_users(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    return BillingService.get_all_user_balances(db)


@router.get("/admin/users/{user_id}/usage", response_model=UsageSummaryResponse)
def admin_get_user_usage(
    user_id: int,
    start_date: str | None = None,
    end_date: str | None = None,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    return BillingService.get_user_usage_summary(db, user_id, start, end)


@router.post("/admin/users/{user_id}/credits", response_model=BalanceResponse)
def admin_add_credits(
    user_id: int,
    body: AddCreditsRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
    svc = BillingService(db, user_id)
    svc.add_credits(
        amount=Decimal(str(body.amount)),
        description=body.description,
        created_by=current_user.id,
    )
    balance = svc.get_balance()
    reserved = svc.get_reserved()
    return {
        "balance": balance,
        "reserved": reserved,
        "available": balance - reserved,
        "currency": "credits",
    }


@router.get("/admin/summary", response_model=PlatformSummaryResponse)
def admin_get_summary(
    start_date: str | None = None,
    end_date: str | None = None,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    return BillingService.get_platform_summary(db, start, end)


@router.get("/admin/logs", response_model=BillingLogListResponse)
def admin_get_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_search: str | None = None,
    provider: str | None = None,
    operation: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get paginated billing logs across all users with filters."""
    query = db.query(UsageRecord, User).join(User, UsageRecord.user_id == User.id)

    if user_search:
        search = f"%{user_search}%"
        query = query.filter(
            (User.email.ilike(search)) | (User.display_name.ilike(search))
        )
    if provider:
        query = query.filter(UsageRecord.provider == provider)
    if operation:
        query = query.filter(UsageRecord.operation == operation)
    if start_date:
        query = query.filter(UsageRecord.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(UsageRecord.created_at <= datetime.fromisoformat(end_date))

    total = query.count()
    rows = (
        query.order_by(UsageRecord.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    items = []
    for record, user in rows:
        items.append({
            "id": record.id,
            "user_id": record.user_id,
            "user_email": user.email,
            "user_display_name": user.display_name,
            "pipeline_log_id": record.pipeline_log_id,
            "operation": record.operation,
            "provider": record.provider,
            "model": record.model,
            "input_tokens": record.input_tokens,
            "output_tokens": record.output_tokens,
            "raw_cost": float(record.raw_cost),
            "charged_cost": float(record.charged_cost),
            "detail": record.detail,
            "created_at": record.created_at.isoformat(),
        })

    return {"items": items, "total": total, "skip": skip, "limit": limit}


def _serialize_catalog_entry(e: CostCatalog) -> dict:
    """Serialize a CostCatalog entry for API responses."""
    return {
        "id": e.id,
        "provider": e.provider,
        "model": e.model,
        "operation": e.operation,
        "cost_per_input_token": float(e.cost_per_input_token) if e.cost_per_input_token else None,
        "cost_per_output_token": float(e.cost_per_output_token) if e.cost_per_output_token else None,
        "cost_per_call": float(e.cost_per_call) if e.cost_per_call else None,
        "platform_markup": float(e.platform_markup),
        "pricing_rules": e.pricing_rules,
        "is_active": e.is_active,
        "created_at": e.created_at.isoformat(),
        "updated_at": e.updated_at.isoformat(),
    }


@router.get("/admin/catalog", response_model=list[CatalogEntryResponse])
def admin_get_catalog(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    entries = BillingService.get_cost_catalog(db)
    return [_serialize_catalog_entry(e) for e in entries]


@router.put("/admin/catalog/model-bulk", response_model=list[CatalogEntryResponse])
def admin_bulk_update_model(
    body: ModelBulkUpdateRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update all catalog entries for a model atomically."""
    # Build lookup of existing entries for this provider/model
    existing = db.query(CostCatalog).filter(
        CostCatalog.provider == body.provider,
        CostCatalog.model == body.model,
    ).all()
    existing_map = {e.operation: e.id for e in existing}

    results = []
    for op_markup in body.operations:
        entry_id = existing_map.get(op_markup.operation)
        entry = BillingService.upsert_catalog_entry(
            db,
            provider=body.provider,
            model=body.model,
            operation=op_markup.operation,
            cost_per_input_token=Decimal(str(body.cost_per_input_token)) if body.cost_per_input_token else None,
            cost_per_output_token=Decimal(str(body.cost_per_output_token)) if body.cost_per_output_token else None,
            cost_per_call=Decimal(str(body.cost_per_call)) if body.cost_per_call else None,
            platform_markup=Decimal(str(op_markup.platform_markup)),
            entry_id=entry_id,
        )
        results.append(_serialize_catalog_entry(entry))
    return results


@router.post("/admin/catalog", response_model=CatalogEntryResponse)
def admin_create_catalog_entry(
    body: CatalogEntryRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = BillingService.upsert_catalog_entry(
        db,
        provider=body.provider,
        model=body.model,
        operation=body.operation,
        cost_per_input_token=Decimal(str(body.cost_per_input_token)) if body.cost_per_input_token else None,
        cost_per_output_token=Decimal(str(body.cost_per_output_token)) if body.cost_per_output_token else None,
        cost_per_call=Decimal(str(body.cost_per_call)) if body.cost_per_call else None,
        platform_markup=Decimal(str(body.platform_markup)),
        pricing_rules=body.pricing_rules,
    )
    return _serialize_catalog_entry(entry)


@router.put("/admin/catalog/{entry_id}", response_model=CatalogEntryResponse)
def admin_update_catalog_entry(
    entry_id: int,
    body: CatalogEntryRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    entry = BillingService.upsert_catalog_entry(
        db,
        provider=body.provider,
        model=body.model,
        operation=body.operation,
        cost_per_input_token=Decimal(str(body.cost_per_input_token)) if body.cost_per_input_token else None,
        cost_per_output_token=Decimal(str(body.cost_per_output_token)) if body.cost_per_output_token else None,
        cost_per_call=Decimal(str(body.cost_per_call)) if body.cost_per_call else None,
        platform_markup=Decimal(str(body.platform_markup)),
        entry_id=entry_id,
        pricing_rules=body.pricing_rules,
    )
    return _serialize_catalog_entry(entry)


@router.delete("/admin/catalog/{entry_id}")
def admin_delete_catalog_entry(
    entry_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    success = BillingService.delete_catalog_entry(db, entry_id)
    if not success:
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    return {"status": "deleted"}


# --- Reconciliation endpoints ---


@router.get("/admin/reconciliation", response_model=ReconciliationResponse)
def admin_get_reconciliation(
    start_date: str | None = None,
    end_date: str | None = None,
    operation: str | None = None,
    provider: str | None = None,
    threshold_pct: float = Query(20.0, ge=0, le=100),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get reconciliation summary: estimated vs actual sparks."""
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    return BillingService.get_reconciliation_summary(
        db, start, end, operation, provider, threshold_pct,
    )


# --- Scatter / Trend endpoints ---


@router.get("/admin/decisions/scatter", response_model=ScatterResponse)
def admin_get_scatter_data(
    hours: int = Query(24, ge=1, le=168),
    operation: str | None = None,
    limit: int = Query(500, ge=1, le=2000),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return individual (estimated, actual) pairs for scatter plot."""
    from datetime import timedelta

    from app.models.cost_decision import CostDecision

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    query = (
        db.query(CostDecision, UsageRecord)
        .join(UsageRecord, UsageRecord.cost_decision_id == CostDecision.id)
        .filter(
            CostDecision.created_at >= cutoff,
            CostDecision.estimated_sparks.isnot(None),
            CostDecision.estimated_sparks > 0,
            UsageRecord.delta_sparks.isnot(None),
            UsageRecord.delta_sparks > 0,
        )
    )
    if operation:
        query = query.filter(CostDecision.operation == operation)

    rows = query.order_by(CostDecision.created_at.desc()).limit(limit).all()
    return {
        "items": [
            {
                "estimated_sparks": d.estimated_sparks,
                "actual_sparks": u.delta_sparks,
                "operation": d.operation,
                "provider": d.provider,
                "created_at": d.created_at.isoformat(),
            }
            for d, u in rows
        ],
    }


@router.get("/admin/anomalies/trend", response_model=TrendResponse)
def admin_get_anomaly_trend(
    hours: int = Query(168, ge=1, le=720),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Return hourly anomaly counts grouped by type."""
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        db.query(
            func.date_trunc("hour", BillingAnomaly.created_at).label("hour"),
            BillingAnomaly.anomaly_type,
            func.count(BillingAnomaly.id).label("cnt"),
        )
        .filter(BillingAnomaly.created_at >= cutoff)
        .group_by("hour", BillingAnomaly.anomaly_type)
        .order_by("hour")
        .all()
    )

    buckets: dict[str, dict[str, int]] = {}
    for row in rows:
        hour_key = row.hour.isoformat()
        if hour_key not in buckets:
            buckets[hour_key] = {}
        buckets[hour_key][row.anomaly_type] = row.cnt

    return {
        "items": [
            {
                "hour": h,
                "total": sum(by_type.values()),
                "by_type": by_type,
            }
            for h, by_type in buckets.items()
        ],
        "hours": hours,
    }


# --- Anomaly endpoints ---


@router.get("/admin/anomalies", response_model=AnomalyListResponse)
def admin_get_anomalies(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    anomaly_type: str | None = None,
    resolved: bool | None = None,
    provider: str | None = None,
    operation: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get paginated anomaly list with filters."""
    query = db.query(BillingAnomaly)
    if anomaly_type:
        query = query.filter(BillingAnomaly.anomaly_type == anomaly_type)
    if resolved is not None:
        query = query.filter(BillingAnomaly.resolved == resolved)
    if provider:
        query = query.filter(BillingAnomaly.provider == provider)
    if operation:
        query = query.filter(BillingAnomaly.operation == operation)
    if start_date:
        query = query.filter(BillingAnomaly.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(BillingAnomaly.created_at <= datetime.fromisoformat(end_date))

    total = query.count()
    rows = query.order_by(BillingAnomaly.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "items": [
            {
                "id": a.id,
                "user_id": a.user_id,
                "anomaly_type": a.anomaly_type,
                "provider": a.provider,
                "model": a.model,
                "operation": a.operation,
                "detail": a.detail,
                "resolved": a.resolved,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/admin/anomalies/summary", response_model=AnomalySummaryResponse)
def admin_get_anomaly_summary(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get anomaly summary: grouped counts + totals."""
    from datetime import timedelta

    groups = (
        db.query(
            BillingAnomaly.anomaly_type,
            BillingAnomaly.provider,
            BillingAnomaly.model,
            BillingAnomaly.operation,
            func.count(BillingAnomaly.id).label("count"),
        )
        .filter(BillingAnomaly.resolved.is_(False))
        .group_by(
            BillingAnomaly.anomaly_type,
            BillingAnomaly.provider,
            BillingAnomaly.model,
            BillingAnomaly.operation,
        )
        .all()
    )
    total_unresolved = (
        db.query(func.count(BillingAnomaly.id))
        .filter(BillingAnomaly.resolved.is_(False))
        .scalar()
    ) or 0
    cutoff_24h = datetime.utcnow() - timedelta(hours=24)
    last_24h_count = (
        db.query(func.count(BillingAnomaly.id))
        .filter(BillingAnomaly.created_at >= cutoff_24h)
        .scalar()
    ) or 0
    return {
        "groups": [
            {
                "anomaly_type": g.anomaly_type,
                "provider": g.provider,
                "model": g.model,
                "operation": g.operation,
                "count": g.count,
            }
            for g in groups
        ],
        "total_unresolved": total_unresolved,
        "last_24h_count": last_24h_count,
    }


@router.patch("/admin/anomalies/{anomaly_id}/resolve")
def admin_resolve_anomaly(
    anomaly_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Mark an anomaly as resolved."""
    anomaly = db.query(BillingAnomaly).filter(BillingAnomaly.id == anomaly_id).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    anomaly.resolved = True
    db.commit()
    return {"status": "resolved", "id": anomaly_id}


@router.post("/admin/anomalies/{anomaly_id}/create-catalog-entry", response_model=CatalogEntryResponse)
def admin_create_catalog_from_anomaly(
    anomaly_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a placeholder catalog entry from an anomaly and mark it resolved."""
    anomaly = db.query(BillingAnomaly).filter(BillingAnomaly.id == anomaly_id).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly not found")
    if not anomaly.provider or not anomaly.model or not anomaly.operation:
        raise HTTPException(status_code=400, detail="Anomaly missing provider/model/operation")

    # Check if entry already exists
    existing = (
        db.query(CostCatalog)
        .filter(
            CostCatalog.provider == anomaly.provider,
            CostCatalog.model == anomaly.model,
            CostCatalog.operation == anomaly.operation,
            CostCatalog.is_active.is_(True),
        )
        .first()
    )
    if existing:
        raise HTTPException(status_code=409, detail="Catalog entry already exists")

    entry = BillingService.upsert_catalog_entry(
        db,
        provider=anomaly.provider,
        model=anomaly.model,
        operation=anomaly.operation,
        cost_per_input_token=Decimal("0"),
        cost_per_output_token=Decimal("0"),
        cost_per_call=Decimal("0"),
        platform_markup=Decimal("2.0"),
    )
    anomaly.resolved = True
    db.commit()

    return {
        "id": entry.id,
        "provider": entry.provider,
        "model": entry.model,
        "operation": entry.operation,
        "cost_per_input_token": float(entry.cost_per_input_token) if entry.cost_per_input_token else None,
        "cost_per_output_token": float(entry.cost_per_output_token) if entry.cost_per_output_token else None,
        "cost_per_call": float(entry.cost_per_call) if entry.cost_per_call else None,
        "platform_markup": float(entry.platform_markup),
        "is_active": entry.is_active,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


# --- Metrics endpoint ---


@router.get("/admin/metrics", response_model=MetricsResponse)
def admin_get_metrics(
    hours: int = Query(24, ge=1, le=168),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get billing health metrics for the given time window."""
    return BillingService.get_metrics(db, hours)


# --- Operations Monitor schemas ---


class CostDecisionResponse(BaseModel):
    id: int
    trace_id: str | None
    user_id: int
    job_id: int | None
    operation: str
    provider: str
    model: str
    catalog_entry_id: int | None
    catalog_match_tier: str | None
    estimated_input_tokens: int | None
    estimated_output_tokens: int | None
    estimated_sparks: int | None
    cost_per_input_token: float | None
    cost_per_output_token: float | None
    cost_per_call: float | None
    platform_markup: float | None
    billing_model: str | None
    image_id: int | None
    resource_id: int | None
    request_snapshot: dict[str, Any] | None
    response_snapshot: dict[str, Any] | None
    status: str
    error_message: str | None
    idempotency_key: str | None
    created_at: str
    updated_at: str


class DecisionListResponse(BaseModel):
    items: list[CostDecisionResponse]
    total: int
    skip: int
    limit: int


class TraceUsageRecordResponse(BaseModel):
    id: int
    user_id: int
    operation: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    raw_cost: float
    charged_cost: float
    cost_decision_id: int | None
    delta_sparks: int | None
    created_at: str


class TracePipelineLogResponse(BaseModel):
    id: int
    category: str
    message: str
    provider: str | None
    model: str | None
    operation: str | None
    duration_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    success: bool | None
    created_at: str


class TraceTransactionResponse(BaseModel):
    id: int
    amount: float
    transaction_type: str
    description: str
    created_at: str


class TraceResponse(BaseModel):
    trace_id: str
    decisions: list[CostDecisionResponse]
    usage_records: list[TraceUsageRecordResponse]
    pipeline_logs: list[TracePipelineLogResponse]
    transactions: list[TraceTransactionResponse]


# --- Operations Monitor endpoints ---


@router.get("/admin/trace/{trace_id}", response_model=TraceResponse)
def admin_get_trace(
    trace_id: str,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Get all billing records associated with a trace ID."""
    from app.models.billing import BalanceTransaction
    from app.models.cost_decision import CostDecision
    from app.models.pipeline_log import PipelineLog

    decisions = (
        db.query(CostDecision)
        .filter(CostDecision.trace_id == trace_id)
        .order_by(CostDecision.created_at)
        .all()
    )
    usage_records = (
        db.query(UsageRecord)
        .filter(UsageRecord.trace_id == trace_id)
        .order_by(UsageRecord.created_at)
        .all()
    )
    pipeline_logs = (
        db.query(PipelineLog)
        .filter(PipelineLog.trace_id == trace_id)
        .order_by(PipelineLog.created_at)
        .all()
    )
    transactions = (
        db.query(BalanceTransaction)
        .filter(BalanceTransaction.trace_id == trace_id)
        .order_by(BalanceTransaction.created_at)
        .all()
    )

    return {
        "trace_id": trace_id,
        "decisions": [
            {
                "id": d.id,
                "trace_id": d.trace_id,
                "user_id": d.user_id,
                "job_id": d.job_id,
                "operation": d.operation,
                "provider": d.provider,
                "model": d.model,
                "catalog_entry_id": d.catalog_entry_id,
                "catalog_match_tier": d.catalog_match_tier,
                "estimated_input_tokens": d.estimated_input_tokens,
                "estimated_output_tokens": d.estimated_output_tokens,
                "estimated_sparks": d.estimated_sparks,
                "cost_per_input_token": float(d.cost_per_input_token) if d.cost_per_input_token else None,
                "cost_per_output_token": float(d.cost_per_output_token) if d.cost_per_output_token else None,
                "cost_per_call": float(d.cost_per_call) if d.cost_per_call else None,
                "platform_markup": float(d.platform_markup) if d.platform_markup else None,
                "billing_model": d.billing_model,
                "image_id": d.image_id,
                "resource_id": d.resource_id,
                "request_snapshot": d.request_snapshot,
                "response_snapshot": d.response_snapshot,
                "status": d.status,
                "error_message": d.error_message,
                "idempotency_key": d.idempotency_key,
                "created_at": d.created_at.isoformat(),
                "updated_at": d.updated_at.isoformat(),
            }
            for d in decisions
        ],
        "usage_records": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "operation": r.operation,
                "provider": r.provider,
                "model": r.model,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "raw_cost": float(r.raw_cost),
                "charged_cost": float(r.charged_cost),
                "cost_decision_id": r.cost_decision_id,
                "delta_sparks": r.delta_sparks,
                "created_at": r.created_at.isoformat(),
            }
            for r in usage_records
        ],
        "pipeline_logs": [
            {
                "id": p.id,
                "category": p.category.value if hasattr(p.category, 'value') else str(p.category),
                "message": p.message,
                "provider": p.provider,
                "model": p.model,
                "operation": p.operation,
                "duration_ms": p.duration_ms,
                "input_tokens": p.input_tokens,
                "output_tokens": p.output_tokens,
                "success": p.success,
                "created_at": p.created_at.isoformat(),
            }
            for p in pipeline_logs
        ],
        "transactions": [
            {
                "id": t.id,
                "amount": t.amount_sparks,
                "transaction_type": t.transaction_type.value if hasattr(t.transaction_type, 'value') else str(t.transaction_type),
                "description": t.description,
                "created_at": t.created_at.isoformat(),
            }
            for t in transactions
        ],
    }


@router.get("/admin/operations", response_model=DecisionListResponse)
def admin_search_operations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    trace_id: str | None = None,
    job_id: int | None = None,
    user_id: int | None = None,
    image_id: int | None = None,
    operation: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Search cost decisions with filters."""
    from app.models.cost_decision import CostDecision

    query = db.query(CostDecision)

    if trace_id:
        query = query.filter(CostDecision.trace_id == trace_id)
    if job_id is not None:
        query = query.filter(CostDecision.job_id == job_id)
    if user_id is not None:
        query = query.filter(CostDecision.user_id == user_id)
    if image_id is not None:
        query = query.filter(CostDecision.image_id == image_id)
    if operation:
        query = query.filter(CostDecision.operation == operation)
    if status:
        query = query.filter(CostDecision.status == status)
    if start_date:
        query = query.filter(CostDecision.created_at >= datetime.fromisoformat(start_date))
    if end_date:
        query = query.filter(CostDecision.created_at <= datetime.fromisoformat(end_date))

    total = query.count()
    rows = (
        query.order_by(CostDecision.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {
        "items": [
            {
                "id": d.id,
                "trace_id": d.trace_id,
                "user_id": d.user_id,
                "job_id": d.job_id,
                "operation": d.operation,
                "provider": d.provider,
                "model": d.model,
                "catalog_entry_id": d.catalog_entry_id,
                "catalog_match_tier": d.catalog_match_tier,
                "estimated_input_tokens": d.estimated_input_tokens,
                "estimated_output_tokens": d.estimated_output_tokens,
                "estimated_sparks": d.estimated_sparks,
                "cost_per_input_token": float(d.cost_per_input_token) if d.cost_per_input_token else None,
                "cost_per_output_token": float(d.cost_per_output_token) if d.cost_per_output_token else None,
                "cost_per_call": float(d.cost_per_call) if d.cost_per_call else None,
                "platform_markup": float(d.platform_markup) if d.platform_markup else None,
                "billing_model": d.billing_model,
                "image_id": d.image_id,
                "resource_id": d.resource_id,
                "request_snapshot": d.request_snapshot,
                "response_snapshot": d.response_snapshot,
                "status": d.status,
                "error_message": d.error_message,
                "idempotency_key": d.idempotency_key,
                "created_at": d.created_at.isoformat(),
                "updated_at": d.updated_at.isoformat(),
            }
            for d in rows
        ],
        "total": total,
        "skip": skip,
        "limit": limit,
    }
