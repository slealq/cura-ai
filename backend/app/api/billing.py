"""Billing API endpoints for user balance, usage, and admin cost management."""
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.security import get_current_user, require_admin
from app.db.base import get_db
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
