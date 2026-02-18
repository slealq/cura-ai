"""Service for credit balance management and usage tracking."""
import logging
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.billing import (
    BalanceTransaction,
    CostCatalog,
    TransactionType,
    UsageRecord,
    UserBalance,
)
from app.models.user import User

logger = logging.getLogger(__name__)

# Balance is denominated in sparks; cost catalog prices are in USD.
# 1 spark = $0.001, so multiply USD by 1000 to get sparks.
USD_TO_SPARKS = Decimal("1000")


class InsufficientBalanceError(Exception):
    """Raised when a user has insufficient credits for an operation."""
    pass


class BillingService:
    """Billing service for a specific user. Follows existing service pattern."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self._user_email: str | None = None

    @property
    def _email(self) -> str:
        """Lazily fetch and cache the user's email for logging."""
        if self._user_email is None:
            user = self.db.query(User.email).filter(User.id == self.user_id).first()
            self._user_email = user.email if user else f"uid:{self.user_id}"
        return self._user_email

    # --- Balance methods ---

    def _get_or_create_balance(self) -> UserBalance:
        """Get or create the UserBalance row for this user."""
        balance = (
            self.db.query(UserBalance)
            .filter(UserBalance.user_id == self.user_id)
            .first()
        )
        if not balance:
            balance = UserBalance(
                user_id=self.user_id,
                balance=Decimal("0"),
                currency="credits",
            )
            self.db.add(balance)
            self.db.commit()
            self.db.refresh(balance)
        return balance

    def get_balance(self) -> Decimal:
        """Get current credit balance."""
        return self._get_or_create_balance().balance

    def has_sufficient_balance(self) -> bool:
        """Check if user has balance > 0."""
        return self.get_balance() > 0

    def check_balance_or_raise(self):
        """Raise InsufficientBalanceError if balance <= 0."""
        if not self.has_sufficient_balance():
            raise InsufficientBalanceError(
                f"User {self.user_id} has insufficient credits"
            )

    def add_credits(
        self, amount: Decimal, description: str, created_by: int | None = None
    ) -> BalanceTransaction:
        """Add credits to user balance. Returns the transaction."""
        balance = self._get_or_create_balance()
        balance.balance += amount
        self.db.flush()

        txn = BalanceTransaction(
            user_id=self.user_id,
            amount=amount,
            transaction_type=TransactionType.CREDIT,
            description=description,
            created_by=created_by,
        )
        self.db.add(txn)
        self.db.commit()
        return txn

    def debit_usage(
        self,
        amount: Decimal,
        description: str,
        usage_record_id: int | None = None,
    ) -> BalanceTransaction:
        """Debit usage from user balance with row-level locking."""
        # SELECT FOR UPDATE to prevent concurrent balance races
        balance = (
            self.db.query(UserBalance)
            .filter(UserBalance.user_id == self.user_id)
            .with_for_update()
            .first()
        )
        if not balance:
            balance = self._get_or_create_balance()
            balance = (
                self.db.query(UserBalance)
                .filter(UserBalance.user_id == self.user_id)
                .with_for_update()
                .first()
            )

        balance.balance -= amount
        self.db.flush()

        txn = BalanceTransaction(
            user_id=self.user_id,
            amount=-amount,
            transaction_type=TransactionType.DEBIT,
            description=description,
            reference_id=usage_record_id,
        )
        self.db.add(txn)
        self.db.commit()
        return txn

    # --- Usage recording ---

    def record_usage(
        self,
        operation: str,
        provider: str,
        model: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        pipeline_log_id: int | None = None,
    ) -> UsageRecord:
        """Record a usage event: look up cost, create record, debit balance."""
        raw_cost, charged_cost, detail = self._calculate_cost(
            provider, model, operation, input_tokens, output_tokens
        )

        record = UsageRecord(
            user_id=self.user_id,
            pipeline_log_id=pipeline_log_id,
            operation=operation,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_cost=raw_cost,
            charged_cost=charged_cost,
            detail=detail,
        )
        self.db.add(record)
        self.db.flush()

        if charged_cost > 0:
            spark_amount = charged_cost * USD_TO_SPARKS
            self.debit_usage(
                amount=spark_amount,
                description=f"{operation} via {provider}/{model}",
                usage_record_id=record.id,
            )

        return record

    def _calculate_cost(
        self,
        provider: str,
        model: str,
        operation: str,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> tuple[Decimal, Decimal, dict | None]:
        """Calculate raw and charged cost from catalog. Returns (raw_cost, charged_cost, detail)."""
        entry = self._get_catalog_entry(provider, model, operation)
        if not entry:
            logger.warning(
                "BILLING MISS | user=%s provider=%s model=%s op=%s "
                "in_tok=%s out_tok=%s — no catalog entry, charging 0",
                self._email, provider, model, operation,
                input_tokens, output_tokens,
            )
            return Decimal("0"), Decimal("0"), None

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
            self._email, provider, model, operation,
            input_tokens, output_tokens,
            float(entry.cost_per_input_token or 0),
            float(entry.cost_per_output_token or 0),
            float(entry.cost_per_call or 0),
            float(raw_cost), float(input_cost), float(output_cost), float(call_cost),
            float(entry.platform_markup),
            float(charged_cost), float(sparks),
        )

        detail = {
            "cost_per_input_token": float(entry.cost_per_input_token or 0),
            "cost_per_output_token": float(entry.cost_per_output_token or 0),
            "cost_per_call": float(entry.cost_per_call or 0),
            "input_cost": float(input_cost),
            "output_cost": float(output_cost),
            "call_cost": float(call_cost),
            "platform_markup": float(entry.platform_markup),
            "sparks": float(sparks),
        }

        return raw_cost, charged_cost, detail

    def _get_catalog_entry(
        self, provider: str, model: str, operation: str
    ) -> CostCatalog | None:
        """Catalog lookup with fallback: exact match -> wildcard model -> None."""
        # Exact match first
        entry = (
            self.db.query(CostCatalog)
            .filter(
                CostCatalog.provider == provider,
                CostCatalog.model == model,
                CostCatalog.operation == operation,
                CostCatalog.is_active.is_(True),
            )
            .first()
        )
        if entry:
            return entry

        # Wildcard model fallback (e.g., fal/* for generate)
        entry = (
            self.db.query(CostCatalog)
            .filter(
                CostCatalog.provider == provider,
                CostCatalog.model == "*",
                CostCatalog.operation == operation,
                CostCatalog.is_active.is_(True),
            )
            .first()
        )
        if entry:
            return entry

        # Partial wildcard (e.g., "openrouter/*" matches "openrouter/qwen...")
        wildcards = (
            self.db.query(CostCatalog)
            .filter(
                CostCatalog.provider == provider,
                CostCatalog.model.like("%*%"),
                CostCatalog.operation == operation,
                CostCatalog.is_active.is_(True),
            )
            .all()
        )
        for wc in wildcards:
            prefix = wc.model.replace("*", "")
            if model.startswith(prefix):
                return wc

        return None

    # --- User-facing reporting ---

    def get_transaction_history(
        self, limit: int = 50, skip: int = 0
    ) -> tuple[list[BalanceTransaction], int]:
        """Get paginated transaction history for this user."""
        query = (
            self.db.query(BalanceTransaction)
            .filter(BalanceTransaction.user_id == self.user_id)
        )
        total = query.count()
        items = (
            query.order_by(BalanceTransaction.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return items, total

    def get_usage_summary(
        self, start_date: datetime | None = None, end_date: datetime | None = None
    ) -> dict:
        """Get aggregated usage summary for this user."""
        query = self.db.query(UsageRecord).filter(
            UsageRecord.user_id == self.user_id
        )
        if start_date:
            query = query.filter(UsageRecord.created_at >= start_date)
        if end_date:
            query = query.filter(UsageRecord.created_at <= end_date)

        records = query.all()

        total_cost = Decimal("0")
        by_operation: dict[str, float] = {}
        by_provider: dict[str, float] = {}

        for r in records:
            sparks = r.charged_cost * USD_TO_SPARKS
            total_cost += sparks
            op_key = r.operation
            by_operation[op_key] = by_operation.get(op_key, 0) + float(sparks)
            by_provider[r.provider] = by_provider.get(r.provider, 0) + float(sparks)

        return {
            "total_cost": float(total_cost),
            "by_operation": by_operation,
            "by_provider": by_provider,
            "record_count": len(records),
        }

    # --- Cost estimation ---

    # Maps frontend base_model → (provider, fal_model_id, operation) for catalog lookup
    GENERATION_MODEL_MAP: dict[str, dict[str, tuple[str, str, str]]] = {
        "flux-dev": {
            "without_lora": ("fal", "fal-ai/flux/dev", "generate"),
            "with_lora": ("fal", "fal-ai/flux-lora", "generate"),
        },
        "qwen-2.5": {
            "without_lora": ("fal", "fal-ai/qwen-image-2512", "generate"),
            "with_lora": ("fal", "fal-ai/qwen-image-2512/lora", "generate"),
        },
        "nano-banana-pro": {
            "without_lora": ("fal", "fal-ai/nano-banana-pro", "generate"),
        },
    }

    @staticmethod
    def get_generation_costs(db: Session) -> dict[str, dict[str, int]]:
        """Get per-image generation costs in sparks for each base model."""
        svc = BillingService(db, user_id=0)  # user_id not used for catalog lookup
        result: dict[str, dict[str, int]] = {}

        for base_model, variants in BillingService.GENERATION_MODEL_MAP.items():
            costs: dict[str, int] = {}
            for variant_key, (provider, model, operation) in variants.items():
                entry = svc._get_catalog_entry(provider, model, operation)
                if entry and entry.cost_per_call:
                    charged_usd = entry.cost_per_call * entry.platform_markup
                    costs[variant_key] = int(charged_usd * USD_TO_SPARKS)
                else:
                    costs[variant_key] = 0
            result[base_model] = costs

        return result

    # --- Admin / reporting (class methods, no user_id filter) ---

    @staticmethod
    def get_cost_catalog(db: Session) -> list[CostCatalog]:
        """Get all active cost catalog entries."""
        return (
            db.query(CostCatalog)
            .filter(CostCatalog.is_active.is_(True))
            .order_by(CostCatalog.provider, CostCatalog.model, CostCatalog.operation)
            .all()
        )

    @staticmethod
    def upsert_catalog_entry(
        db: Session,
        provider: str,
        model: str,
        operation: str,
        cost_per_input_token: Decimal | None = None,
        cost_per_output_token: Decimal | None = None,
        cost_per_call: Decimal | None = None,
        platform_markup: Decimal = Decimal("2.0"),
        entry_id: int | None = None,
    ) -> CostCatalog:
        """Create or update a cost catalog entry."""
        if entry_id:
            entry = db.query(CostCatalog).filter(CostCatalog.id == entry_id).first()
            if entry:
                entry.provider = provider
                entry.model = model
                entry.operation = operation
                entry.cost_per_input_token = cost_per_input_token
                entry.cost_per_output_token = cost_per_output_token
                entry.cost_per_call = cost_per_call
                entry.platform_markup = platform_markup
                db.commit()
                return entry

        entry = CostCatalog(
            provider=provider,
            model=model,
            operation=operation,
            cost_per_input_token=cost_per_input_token,
            cost_per_output_token=cost_per_output_token,
            cost_per_call=cost_per_call,
            platform_markup=platform_markup,
        )
        db.add(entry)
        db.commit()
        return entry

    @staticmethod
    def delete_catalog_entry(db: Session, entry_id: int) -> bool:
        """Soft-delete a catalog entry."""
        entry = db.query(CostCatalog).filter(CostCatalog.id == entry_id).first()
        if not entry:
            return False
        entry.is_active = False
        db.commit()
        return True

    @staticmethod
    def get_all_user_balances(db: Session) -> list[dict]:
        """Get all user balances joined with user info for admin dashboard."""
        results = (
            db.query(User, UserBalance)
            .outerjoin(UserBalance, User.id == UserBalance.user_id)
            .filter(User.is_active.is_(True))
            .all()
        )

        # Get total spent per user
        spent_query = (
            db.query(
                UsageRecord.user_id,
                func.sum(UsageRecord.charged_cost).label("total_spent"),
                func.max(UsageRecord.created_at).label("last_activity"),
            )
            .group_by(UsageRecord.user_id)
            .all()
        )
        spent_map = {r.user_id: {"total_spent": float((r.total_spent or 0) * USD_TO_SPARKS), "last_activity": r.last_activity} for r in spent_query}

        output = []
        for user, balance in results:
            spent_info = spent_map.get(user.id, {"total_spent": 0, "last_activity": None})
            output.append({
                "user_id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "balance": float(balance.balance) if balance else 0,
                "total_spent": spent_info["total_spent"],
                "last_activity": spent_info["last_activity"].isoformat() if spent_info["last_activity"] else None,
            })
        return output

    @staticmethod
    def get_user_usage_summary(
        db: Session, user_id: int, start_date: datetime | None = None, end_date: datetime | None = None
    ) -> dict:
        """Get usage summary for a specific user (admin view)."""
        svc = BillingService(db, user_id)
        return svc.get_usage_summary(start_date, end_date)

    @staticmethod
    def get_platform_summary(
        db: Session, start_date: datetime | None = None, end_date: datetime | None = None
    ) -> dict:
        """Get platform-wide usage aggregation."""
        query = db.query(UsageRecord)
        if start_date:
            query = query.filter(UsageRecord.created_at >= start_date)
        if end_date:
            query = query.filter(UsageRecord.created_at <= end_date)

        records = query.all()

        total_raw = Decimal("0")
        total_charged = Decimal("0")
        by_provider: dict[str, float] = {}
        by_operation: dict[str, float] = {}

        for r in records:
            total_raw += r.raw_cost
            total_charged += r.charged_cost
            sparks = r.charged_cost * USD_TO_SPARKS
            by_provider[r.provider] = by_provider.get(r.provider, 0) + float(sparks)
            by_operation[r.operation] = by_operation.get(r.operation, 0) + float(sparks)

        return {
            "total_raw_cost": float(total_raw),
            "total_charged": float(total_charged * USD_TO_SPARKS),
            "margin": float(total_charged - total_raw),
            "by_provider": by_provider,
            "by_operation": by_operation,
            "record_count": len(records),
        }


def record_usage_standalone(
    user_id: int,
    provider: str,
    model: str,
    operation: str,
    input_tokens: int | None,
    output_tokens: int | None,
    pipeline_log_id: int | None,
) -> None:
    """Record usage in its own session. Called from write_log after-hook."""
    db = SessionLocal()
    try:
        svc = BillingService(db, user_id)
        svc.record_usage(
            operation=operation,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pipeline_log_id=pipeline_log_id,
        )
    except Exception as e:
        logger.warning(f"Failed to record usage for user {user_id}: {e}")
        db.rollback()
    finally:
        db.close()
