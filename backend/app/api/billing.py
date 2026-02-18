"""Billing API endpoints for user balance, usage, and admin cost management."""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.db.base import get_db
from app.models.billing import UsageRecord
from app.models.user import User
from app.services.billing_service import BillingService

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
    # Estimate expand_prompt cost: ~100 input tokens, ~200 output tokens typical
    svc = BillingService(db, user_id=0)
    entry = svc._get_catalog_entry("openai", "gpt-4o-mini", "expand_prompt")
    expand_cost = 0.0
    if entry and entry.cost_per_input_token and entry.cost_per_output_token:
        from decimal import Decimal
        raw = entry.cost_per_input_token * 100 + entry.cost_per_output_token * 200
        charged = raw * entry.platform_markup
        expand_cost = float(charged * Decimal("1000"))  # USD to sparks
    return {
        "costs": BillingService.get_generation_costs(db),
        "expand_prompt_cost": round(expand_cost, 1),
    }


class VisionCostsResponse(BaseModel):
    """Estimated per-call vision cost in sparks by provider and mode."""
    costs: dict[str, dict[str, float]]


# Typical token estimates for vision calls.
# Output tokens (per mode) are conservative estimates (below max_tokens limits).
_VISION_OUTPUT_TOKENS = {"tag": 500, "describe": 1500, "custom": 1000}

# Input tokens differ dramatically by provider due to image tokenization:
#   OpenAI gpt-4o: ~765 tokens per high-detail image + ~400 prompt/system ≈ 1200
#   Anthropic Claude: similar to OpenAI, ~1200
#   fal/OpenRouter (Grok): images consume ~50-60K tokens (observed from billing data)
#     Plus fal.ai adds ~1.8x markup over raw OpenRouter cost.
_VISION_INPUT_TOKENS = {
    "openai": 1200,
    "anthropic": 1200,
    "fal": 55000,
}

# fal.ai charges ~1.8x more than raw OpenRouter token cost (their intermediary markup)
_FAL_INTERMEDIARY_MARKUP = Decimal("1.8")

# Map provider → (catalog_provider, catalog_model)
_VISION_PROVIDER_MAP = {
    "openai": ("openai", "gpt-4o"),
    "anthropic": ("anthropic", "claude-sonnet-4-20250514"),
    "fal": ("fal", "x-ai/grok-4-fast"),
}


@router.get("/vision-costs", response_model=VisionCostsResponse)
def get_vision_costs(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get estimated per-call vision cost in sparks for each provider and mode."""
    svc = BillingService(db, user_id=0)
    result: dict[str, dict[str, float]] = {}

    for provider_key, (cat_provider, cat_model) in _VISION_PROVIDER_MAP.items():
        costs: dict[str, float] = {}
        input_tokens = _VISION_INPUT_TOKENS.get(provider_key, 1200)
        for mode, output_tokens in _VISION_OUTPUT_TOKENS.items():
            # tag and describe have catalog entries; custom uses describe pricing
            operation = "tag" if mode == "tag" else "describe"
            entry = svc._get_catalog_entry(cat_provider, cat_model, operation)
            if entry and entry.cost_per_input_token and entry.cost_per_output_token:
                raw = (entry.cost_per_input_token * input_tokens
                       + entry.cost_per_output_token * output_tokens)
                # fal.ai adds its own intermediary markup on top of OpenRouter
                if provider_key == "fal":
                    raw = raw * _FAL_INTERMEDIARY_MARKUP
                charged = raw * entry.platform_markup
                costs[mode] = round(float(charged * Decimal("1000")), 1)
            else:
                costs[mode] = 0
        result[provider_key] = costs

    return {"costs": result}


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
