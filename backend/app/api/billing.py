"""Billing API endpoints for user balance, usage, and admin cost management."""
import logging
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.settings import (
    CURATED_OPENAI_VISION_MODELS,
    _get_anthropic_models,
    _get_fal_models,
)
from app.core.security import get_current_user, require_admin
from app.db.base import get_db
from app.models.billing import CostCatalog, UsageRecord
from app.models.user import User
from app.services.billing_service import BillingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["billing"])


# --- Pydantic schemas ---

class BalanceResponse(BaseModel):
    balance: float
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


class UsageSummaryResponse(BaseModel):
    total_cost: float
    by_operation: dict[str, float]
    by_provider: dict[str, float]
    record_count: int


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
    costs: dict[str, dict[str, int]]
    expand_prompt_cost: float


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


# --- User endpoints ---

@router.get("/balance", response_model=BalanceResponse)
def get_balance(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc = BillingService(db, current_user.id)
    balance = svc.get_balance()
    return {"balance": float(balance), "currency": "credits"}


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
                "amount": float(t.amount),
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

    svc = BillingService(db, user_id=0)
    entry = svc._get_catalog_entry("openai", "gpt-4o-mini", "expand_prompt")
    expand_cost = 0.0
    if entry and entry.cost_per_input_token and entry.cost_per_output_token:
        # Estimate from typical prompt length (~100 tokens) and DB avg or default 200
        input_tokens = estimate_prompt_tokens("Expand this prompt into a detailed description")
        db_avg_out = BillingService.get_average_output_tokens(
            db, "openai", "gpt-4o-mini", "expand_prompt",
        )
        output_tokens = db_avg_out if db_avg_out is not None else 200
        raw = entry.cost_per_input_token * input_tokens + entry.cost_per_output_token * output_tokens
        charged = raw * entry.platform_markup
        expand_cost = float(charged * Decimal("1000"))  # USD to sparks
    return {
        "costs": BillingService.get_generation_costs(db),
        "expand_prompt_cost": round(expand_cost, 1),
    }


class EditCostsResponse(BaseModel):
    """Per-call edit cost in sparks by edit model."""
    costs: dict[str, int]


class TrainingCostsResponse(BaseModel):
    """Per-job training cost in sparks by base model."""
    costs: dict[str, int]


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

    svc = BillingService(db, user_id=0)

    # Get user's active composed prompt text
    settings_svc = SettingsService(db, user_id)
    tag_prompt_text = settings_svc.get_tag_prompt()
    desc_prompt_text = settings_svc.get_description_prompt()

    # Embed cost (always OpenAI text-embedding-3-small)
    embed_entry = svc._get_catalog_entry("openai", "text-embedding-3-small", "embed")
    embed_tokens = estimate_embed_tokens()
    embed_cost_sparks = 0.0
    if embed_entry and embed_entry.cost_per_input_token:
        raw = embed_entry.cost_per_input_token * embed_tokens
        charged = raw * embed_entry.platform_markup
        embed_cost_sparks = round(float(charged * Decimal("1000")), 1)

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

                entry = svc._get_catalog_entry(cat_provider, model_id, operation)
                if entry and entry.cost_per_input_token and entry.cost_per_output_token:
                    in_cost = entry.cost_per_input_token * input_tokens
                    out_cost = entry.cost_per_output_token * output_tokens
                    raw = in_cost + out_cost
                    charged = raw * entry.platform_markup
                    sparks = round(float(charged * Decimal("1000")), 1)
                    costs[mode] = sparks
                    logger.info(
                        "ESTIMATE | %s/%s %s %dx%d | "
                        "img_tok=%d + prompt_tok=%d(%dchars) = in=%d | "
                        "out=%d | "
                        "in_cost=$%.6f + out_cost=$%.6f = raw=$%.6f | "
                        "markup=%.1fx → sparks=%.1f",
                        cat_provider, model_id, mode, width, height,
                        img_tokens, prompt_tokens, len(prompt_text), input_tokens,
                        output_tokens,
                        float(in_cost), float(out_cost), float(raw),
                        float(entry.platform_markup), sparks,
                    )
                else:
                    costs[mode] = 0

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
    return {"balance": float(balance), "currency": "credits"}


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


@router.get("/admin/catalog", response_model=list[CatalogEntryResponse])
def admin_get_catalog(
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    entries = BillingService.get_cost_catalog(db)
    return [
        {
            "id": e.id,
            "provider": e.provider,
            "model": e.model,
            "operation": e.operation,
            "cost_per_input_token": float(e.cost_per_input_token) if e.cost_per_input_token else None,
            "cost_per_output_token": float(e.cost_per_output_token) if e.cost_per_output_token else None,
            "cost_per_call": float(e.cost_per_call) if e.cost_per_call else None,
            "platform_markup": float(e.platform_markup),
            "is_active": e.is_active,
            "created_at": e.created_at.isoformat(),
            "updated_at": e.updated_at.isoformat(),
        }
        for e in entries
    ]


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
        results.append({
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
        })
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
    )
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
    )
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
