"""Service for credit balance management and usage tracking."""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.billing import (
    BalanceTransaction,
    BillingAnomaly,
    CostCatalog,
    TransactionType,
    UsageRecord,
    UserBalance,
)
from app.models.cost_decision import CostDecision
from app.models.user import User
from app.services.cost_calculator import USD_TO_SPARKS
from app.services.cost_calculator import calculate_cost as _calc_cost
from app.services.cost_calculator import estimate_sparks as _estimate_sparks
from app.services.cost_calculator import get_catalog_entry as _get_catalog

logger = logging.getLogger(__name__)


class InsufficientBalanceError(Exception):
    """Raised when a user has insufficient credits for an operation."""
    pass


class CatalogMissError(Exception):
    """Raised in strict mode when no catalog entry matches a billed operation."""
    pass


class ZeroCostEstimateError(Exception):
    """Raised when an operation estimates to 0 sparks — billing config is broken."""
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
                balance_sparks=0,
                reserved_sparks=0,
                currency="credits",
            )
            self.db.add(balance)
            self.db.commit()
            self.db.refresh(balance)
        return balance

    def get_balance(self) -> int:
        """Get current credit balance in integer sparks."""
        return self._get_or_create_balance().balance_sparks

    def get_available_balance(self) -> int:
        """Get available balance (balance - reserved) in integer sparks."""
        bal = self._get_or_create_balance()
        return bal.balance_sparks - bal.reserved_sparks

    def get_reserved(self) -> int:
        """Get total reserved sparks."""
        return self._get_or_create_balance().reserved_sparks

    def has_sufficient_balance(self) -> bool:
        """Check if user has available balance > 0."""
        return self.get_available_balance() > 0

    def check_balance_or_raise(self):
        """Raise InsufficientBalanceError if available balance <= 0."""
        if not self.has_sufficient_balance():
            raise InsufficientBalanceError(
                f"User {self.user_id} has insufficient credits"
            )

    # --- Reservation methods ---

    def reserve_sparks(self, amount: int, decision_id: int | None = None) -> bool:
        """Atomically reserve sparks for an upcoming operation.

        Uses UPDATE ... WHERE to ensure (balance_sparks - reserved_sparks) >= amount.
        Returns False if insufficient available balance.
        """
        if amount <= 0:
            return True

        self._get_or_create_balance()

        rows_updated = (
            self.db.query(UserBalance)
            .filter(
                UserBalance.user_id == self.user_id,
                (UserBalance.balance_sparks - UserBalance.reserved_sparks) >= amount,
            )
            .update(
                {UserBalance.reserved_sparks: UserBalance.reserved_sparks + amount},
                synchronize_session="fetch",
            )
        )
        if rows_updated == 0:
            return False

        self.db.flush()
        logger.info(
            "RESERVE | user=%s amount=%d decision=%s",
            self.user_id, amount, decision_id,
        )
        return True

    def release_reservation(self, amount: int) -> None:
        """Release a reservation, clamping reserved_sparks to 0 floor."""
        if not amount or amount <= 0:
            return

        self._get_or_create_balance()

        # Use GREATEST to clamp to 0
        self.db.execute(
            UserBalance.__table__.update()
            .where(UserBalance.user_id == self.user_id)
            .values(reserved_sparks=func.greatest(
                UserBalance.reserved_sparks - amount, 0
            ))
        )
        self.db.flush()
        logger.info(
            "RELEASE_RESERVATION | user=%s amount=%d", self.user_id, amount,
        )

    def release_and_debit(
        self, reserved_amount: int, actual_amount: Decimal, description: str,
        usage_record_id: int | None = None,
    ) -> None:
        """Release reservation then debit actual cost in one transaction."""
        self.release_reservation(reserved_amount)
        if actual_amount > 0:
            self.debit_usage(
                amount=actual_amount,
                description=description,
                usage_record_id=usage_record_id,
            )

    def add_credits(
        self, amount: Decimal, description: str, created_by: int | None = None
    ) -> BalanceTransaction:
        """Add credits to user balance. Returns the transaction."""
        balance = self._get_or_create_balance()
        balance.balance += amount
        balance.balance_sparks += int(amount)
        self.db.flush()

        txn = BalanceTransaction(
            user_id=self.user_id,
            amount=amount,
            amount_sparks=int(amount),
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
        """Debit usage from user balance with atomic conditional update.

        Uses UPDATE ... WHERE balance >= amount to prevent negative balance
        via TOCTOU race. Raises InsufficientBalanceError if balance is too low.
        """
        # Ensure the balance row exists
        self._get_or_create_balance()

        # Atomic: only debit if balance >= amount (dual-write both columns)
        int_amount = int(amount)
        rows_updated = (
            self.db.query(UserBalance)
            .filter(
                UserBalance.user_id == self.user_id,
                UserBalance.balance >= amount,
            )
            .update(
                {
                    UserBalance.balance: UserBalance.balance - amount,
                    UserBalance.balance_sparks: UserBalance.balance_sparks - int_amount,
                },
                synchronize_session="fetch",
            )
        )
        if rows_updated == 0:
            self.db.rollback()
            raise InsufficientBalanceError(
                f"User {self.user_id} has insufficient credits (need {amount} sparks)"
            )

        self.db.flush()

        from app.services.billing_context import get_trace_id

        txn = BalanceTransaction(
            user_id=self.user_id,
            amount=-amount,
            amount_sparks=-int_amount,
            transaction_type=TransactionType.DEBIT,
            description=description,
            reference_id=usage_record_id,
            trace_id=get_trace_id(),
        )
        self.db.add(txn)
        try:
            self.db.commit()
        except IntegrityError:
            # Duplicate debit for this usage record — partial unique index caught it
            self.db.rollback()
            logger.warning(
                "Duplicate debit blocked for user=%s reference_id=%s",
                self.user_id, usage_record_id,
            )
            # Return the existing transaction
            existing = (
                self.db.query(BalanceTransaction)
                .filter(
                    BalanceTransaction.user_id == self.user_id,
                    BalanceTransaction.reference_id == usage_record_id,
                    BalanceTransaction.transaction_type == TransactionType.DEBIT,
                )
                .first()
            )
            if existing:
                return existing
            # Shouldn't happen, but re-raise if we can't find it
            raise
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
        provider_cost: float | None = None,
        defer_debit: bool = False,
    ) -> UsageRecord:
        """Record a usage event: look up cost, create record, debit balance.

        When defer_debit=True, the UsageRecord is created but the balance
        debit is skipped — the caller is responsible for debiting later
        (e.g. finalize_pipeline_billing).
        """
        raw_cost, charged_cost, detail = self._calculate_cost(
            provider, model, operation, input_tokens, output_tokens,
            provider_cost=provider_cost,
        )

        from app.services.billing_context import get_trace_id

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
            trace_id=get_trace_id(),
        )
        self.db.add(record)
        self.db.flush()

        if charged_cost > 0 and not defer_debit:
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
        provider_cost: float | None = None,
    ) -> tuple[Decimal, Decimal, dict | None]:
        """Calculate raw and charged cost. Delegates to cost_calculator, then handles anomalies."""
        raw_cost, charged_cost, detail = _calc_cost(
            self.db, provider, model, operation,
            input_tokens, output_tokens,
            provider_cost=provider_cost,
            user_email=self._email,
        )

        # Handle catalog miss: record anomaly + strict mode check
        if detail and detail.get("catalog_match_tier") == "none" and provider_cost is None:
            try:
                from app.models.billing import BillingAnomaly
                anomaly = BillingAnomaly(
                    user_id=self.user_id if self.user_id else None,
                    anomaly_type="catalog_miss",
                    provider=provider,
                    model=model,
                    operation=operation,
                    detail={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                    },
                )
                self.db.add(anomaly)
                self.db.commit()
            except Exception:
                logger.warning("Failed to record billing anomaly", exc_info=True)
                self.db.rollback()

            from app.core.config import get_settings
            if get_settings().billing_strict_mode:
                raise CatalogMissError(
                    f"No catalog entry for {provider}/{model}/{operation}"
                )

        return raw_cost, charged_cost, detail

    def _get_catalog_entry(
        self, provider: str, model: str, operation: str
    ) -> tuple[CostCatalog | None, str]:
        """Catalog lookup. Delegates to cost_calculator."""
        return _get_catalog(self.db, provider, model, operation)

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

        total_cost = 0
        by_operation: dict[str, int] = {}
        by_provider: dict[str, int] = {}

        for r in records:
            sparks = r.delta_sparks if r.delta_sparks is not None else int(r.charged_cost * USD_TO_SPARKS)
            total_cost += sparks
            op_key = r.operation
            by_operation[op_key] = by_operation.get(op_key, 0) + sparks
            by_provider[r.provider] = by_provider.get(r.provider, 0) + sparks

        return {
            "total_cost": total_cost,
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
        result: dict[str, dict[str, int]] = {}

        for base_model, variants in BillingService.GENERATION_MODEL_MAP.items():
            costs: dict[str, int] = {}
            for variant_key, (provider, model, operation) in variants.items():
                sparks, _ = _estimate_sparks(db, provider, model, operation)
                costs[variant_key] = sparks
            result[base_model] = costs

        return result

    # Maps frontend edit model key → (provider, catalog model ID, operation)
    EDIT_MODEL_MAP: dict[str, tuple[str, str, str]] = {
        "qwen-image-max-edit": ("fal", "fal-ai/qwen-image-max/edit", "edit"),
        "kling-image": ("fal", "fal-ai/kling-image/o3/image-to-image", "edit"),
        "wan-25": ("fal", "fal-ai/wan-25-preview/image-to-image", "edit"),
        "grok-imagine": ("fal", "xai/grok-imagine-image/edit", "edit"),
        "face-swap": ("fal", "half-moon-ai/ai-face-swap/faceswapimage", "edit"),
        "nano-banana-pro-edit": ("fal", "fal-ai/nano-banana-pro/edit", "edit"),
    }

    # Maps frontend base model key → (provider, catalog model ID, operation)
    TRAINING_MODEL_MAP: dict[str, tuple[str, str, str]] = {
        "flux-dev": ("fal", "fal-ai/flux-lora-fast-training", "train"),
        "qwen-2.5": ("fal", "fal-ai/qwen-image-2512-trainer-v2", "train"),
    }

    @staticmethod
    def get_edit_costs(db: Session) -> dict[str, int]:
        """Get per-call edit costs in sparks for each edit model.

        Uses flat cost_per_call from catalog — approximate for typical resolutions.
        Post-run billing uses fal.ai's actual reported cost which accounts for
        resolution and output count variation.
        """
        result: dict[str, int] = {}
        for edit_model, (provider, model, operation) in BillingService.EDIT_MODEL_MAP.items():
            sparks, _ = _estimate_sparks(db, provider, model, operation)
            result[edit_model] = sparks
        return result

    @staticmethod
    def get_training_costs(db: Session) -> dict[str, int]:
        """Get per-job training costs in sparks for each base model."""
        result: dict[str, int] = {}
        for base_model, (provider, model, operation) in BillingService.TRAINING_MODEL_MAP.items():
            sparks, _ = _estimate_sparks(db, provider, model, operation)
            result[base_model] = sparks
        return result

    # --- Reconciliation & Metrics ---

    @staticmethod
    def get_reconciliation_summary(
        db: Session,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        operation: str | None = None,
        provider: str | None = None,
        threshold_pct: float = 20.0,
    ) -> dict:
        """Reconcile estimated vs actual sparks across cost decisions."""
        query = (
            db.query(
                CostDecision.operation,
                CostDecision.provider,
                CostDecision.model,
                func.count(CostDecision.id).label("total_decisions"),
                func.avg(CostDecision.estimated_sparks).label("avg_estimated"),
                func.avg(UsageRecord.delta_sparks).label("avg_actual"),
                func.min(UsageRecord.delta_sparks - CostDecision.estimated_sparks).label("min_delta"),
                func.max(UsageRecord.delta_sparks - CostDecision.estimated_sparks).label("max_delta"),
                func.sum(CostDecision.estimated_sparks).label("total_estimated"),
                func.sum(UsageRecord.delta_sparks).label("total_actual"),
            )
            .join(UsageRecord, UsageRecord.cost_decision_id == CostDecision.id)
            .filter(
                CostDecision.status.in_(["charged", "executed"]),
                CostDecision.estimated_sparks.isnot(None),
                UsageRecord.delta_sparks.isnot(None),
            )
        )
        if start_date:
            query = query.filter(CostDecision.created_at >= start_date)
        if end_date:
            query = query.filter(CostDecision.created_at <= end_date)
        if operation:
            query = query.filter(CostDecision.operation == operation)
        if provider:
            query = query.filter(CostDecision.provider == provider)

        query = query.group_by(CostDecision.operation, CostDecision.provider, CostDecision.model)
        rows = query.all()

        items = []
        threshold_violations = 0
        for row in rows:
            avg_est = float(row.avg_estimated or 0)
            avg_act = float(row.avg_actual or 0)
            avg_delta = avg_act - avg_est
            avg_delta_pct = (avg_delta / avg_est * 100) if avg_est != 0 else 0.0
            if abs(avg_delta_pct) > threshold_pct:
                threshold_violations += 1
            items.append({
                "operation": row.operation,
                "provider": row.provider,
                "model": row.model,
                "total_decisions": row.total_decisions,
                "avg_estimated_sparks": round(avg_est, 1),
                "avg_actual_sparks": round(avg_act, 1),
                "avg_delta": round(avg_delta, 1),
                "avg_delta_pct": round(avg_delta_pct, 1),
                "min_delta": float(row.min_delta or 0),
                "max_delta": float(row.max_delta or 0),
                "total_estimated": int(row.total_estimated or 0),
                "total_actual": int(row.total_actual or 0),
            })

        return {
            "items": items,
            "threshold_pct": threshold_pct,
            "threshold_violations": threshold_violations,
        }

    @staticmethod
    def get_metrics(db: Session, hours: int = 24) -> dict:
        """Get billing health metrics for the given time window."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # Decision counts
        total_ops = (
            db.query(func.count(CostDecision.id))
            .filter(CostDecision.created_at >= cutoff)
            .scalar()
        ) or 0

        failed_count = (
            db.query(func.count(CostDecision.id))
            .filter(CostDecision.created_at >= cutoff, CostDecision.status == "failed")
            .scalar()
        ) or 0

        cancelled_count = (
            db.query(func.count(CostDecision.id))
            .filter(CostDecision.created_at >= cutoff, CostDecision.status == "cancelled")
            .scalar()
        ) or 0

        # Stale pending decisions (> 30 min old)
        stale_cutoff = datetime.utcnow() - timedelta(minutes=30)
        pending_decisions = (
            db.query(func.count(CostDecision.id))
            .filter(
                CostDecision.status == "pending",
                CostDecision.created_at < stale_cutoff,
            )
            .scalar()
        ) or 0

        # Average delta percentage
        avg_delta_pct_row = (
            db.query(
                func.avg(
                    (UsageRecord.delta_sparks - CostDecision.estimated_sparks)
                    * 100.0
                    / func.nullif(CostDecision.estimated_sparks, 0)
                )
            )
            .join(UsageRecord, UsageRecord.cost_decision_id == CostDecision.id)
            .filter(
                CostDecision.created_at >= cutoff,
                CostDecision.estimated_sparks.isnot(None),
                UsageRecord.delta_sparks.isnot(None),
            )
            .scalar()
        )
        avg_delta_pct = round(float(avg_delta_pct_row), 1) if avg_delta_pct_row is not None else 0.0

        # Catalog misses
        catalog_miss_count = (
            db.query(func.count(BillingAnomaly.id))
            .filter(
                BillingAnomaly.anomaly_type == "catalog_miss",
                BillingAnomaly.created_at >= cutoff,
            )
            .scalar()
        ) or 0

        failure_rate = failed_count / total_ops if total_ops > 0 else 0.0
        cancel_rate = cancelled_count / total_ops if total_ops > 0 else 0.0
        ops_per_hour = total_ops / hours if hours > 0 else 0.0

        # By operation breakdown
        by_operation = (
            db.query(
                CostDecision.operation,
                func.count(CostDecision.id).label("count"),
                func.avg(
                    case(
                        (UsageRecord.delta_sparks.isnot(None), UsageRecord.delta_sparks),
                        else_=CostDecision.estimated_sparks,
                    )
                ).label("avg_sparks"),
                func.count(
                    case((CostDecision.status == "failed", CostDecision.id))
                ).label("failure_count"),
            )
            .outerjoin(UsageRecord, UsageRecord.cost_decision_id == CostDecision.id)
            .filter(CostDecision.created_at >= cutoff)
            .group_by(CostDecision.operation)
            .all()
        )

        # By provider breakdown
        by_provider = (
            db.query(
                CostDecision.provider,
                func.count(CostDecision.id).label("count"),
                func.avg(
                    case(
                        (UsageRecord.delta_sparks.isnot(None), UsageRecord.delta_sparks),
                        else_=CostDecision.estimated_sparks,
                    )
                ).label("avg_sparks"),
                func.count(
                    case((CostDecision.status == "failed", CostDecision.id))
                ).label("failure_count"),
            )
            .outerjoin(UsageRecord, UsageRecord.cost_decision_id == CostDecision.id)
            .filter(CostDecision.created_at >= cutoff)
            .group_by(CostDecision.provider)
            .all()
        )

        # Alerts
        alerts = []
        if failure_rate > 0.10:
            alerts.append({"level": "warning", "message": f"High failure rate: {failure_rate:.1%}"})
        if catalog_miss_count > 5:
            alerts.append({"level": "warning", "message": f"{catalog_miss_count} catalog misses in {hours}h"})
        if pending_decisions > 10:
            alerts.append({"level": "critical", "message": f"{pending_decisions} stale pending decisions (>30min)"})

        return {
            "hours": hours,
            "total_operations": total_ops,
            "ops_per_hour": round(ops_per_hour, 1),
            "failure_rate": round(failure_rate, 4),
            "cancel_rate": round(cancel_rate, 4),
            "pending_decisions": pending_decisions,
            "avg_delta_pct": avg_delta_pct,
            "catalog_miss_count": catalog_miss_count,
            "by_operation": [
                {
                    "operation": row.operation,
                    "count": row.count,
                    "avg_sparks": round(float(row.avg_sparks or 0), 1),
                    "failure_count": row.failure_count,
                }
                for row in by_operation
            ],
            "by_provider": [
                {
                    "provider": row.provider,
                    "count": row.count,
                    "avg_sparks": round(float(row.avg_sparks or 0), 1),
                    "failure_count": row.failure_count,
                }
                for row in by_provider
            ],
            "alerts": alerts,
        }

    @staticmethod
    def get_evaluation_costs(
        db: Session,
        user_id: int,
        base_model: str = "flux-dev",
        sample_count: int = 5,
        creative_count: int = 0,
        vision_eval_provider: str | None = None,
    ) -> dict:
        """Estimate evaluation costs broken down by sub-operation."""
        from app.services.settings_service import SettingsService

        settings = SettingsService(db, user_id)
        provider_config = settings.get_provider_config()

        # Resolve generation model for this base_model (with_lora variant)
        gen_map = BillingService.GENERATION_MODEL_MAP.get(base_model, {})
        gen_variant = gen_map.get("with_lora", gen_map.get("without_lora"))
        if gen_variant:
            gen_provider, gen_model, gen_op = gen_variant
        else:
            gen_provider, gen_model, gen_op = "fal", "fal-ai/flux-lora", "generate"

        generate_sparks, _ = _estimate_sparks(db, gen_provider, gen_model, gen_op)

        # Vision/describe provider
        vision_provider_key = provider_config.get("vision_provider", "openai")
        if vision_provider_key == "openai":
            vision_model = provider_config.get("openai_vision_model", "gpt-4o-mini")
            vision_prov = "openai"
        elif vision_provider_key == "anthropic":
            vision_model = provider_config.get("anthropic_vision_model", "claude-sonnet-4-20250514")
            vision_prov = "anthropic"
        else:
            vision_model = provider_config.get("fal_vision_model", "x-ai/grok-2-vision-1212")
            vision_prov = "fal"

        # Eval provider (override or same as vision)
        if vision_eval_provider:
            eval_prov = vision_eval_provider
            if eval_prov == "openai":
                eval_model = provider_config.get("openai_vision_model", "gpt-4o-mini")
            elif eval_prov == "anthropic":
                eval_model = provider_config.get("anthropic_vision_model", "claude-sonnet-4-20250514")
            else:
                eval_model = provider_config.get("fal_vision_model", "x-ai/grok-2-vision-1212")
        else:
            eval_prov = vision_prov
            eval_model = vision_model

        describe_sparks, _ = _estimate_sparks(
            db, vision_prov, vision_model, "describe",
            estimated_input_tokens=1500, estimated_output_tokens=500,
        )
        embed_sparks, _ = _estimate_sparks(
            db, "openai", "text-embedding-3-small", "embed",
            estimated_input_tokens=500,
        )
        vision_eval_sparks, _ = _estimate_sparks(
            db, eval_prov, eval_model, "evaluate",
            estimated_input_tokens=2000, estimated_output_tokens=300,
        )

        # Creative prompts generation (one-time call)
        creative_prompts_sparks, _ = _estimate_sparks(
            db, eval_prov, eval_model, "evaluate",
            estimated_input_tokens=2000, estimated_output_tokens=500,
        ) if creative_count > 0 else (0, None)

        # Assessment (one-time call)
        assessment_sparks, _ = _estimate_sparks(
            db, eval_prov, eval_model, "evaluate",
            estimated_input_tokens=3000, estimated_output_tokens=800,
        )

        per_ref = generate_sparks + describe_sparks + embed_sparks + vision_eval_sparks
        per_creative = generate_sparks + vision_eval_sparks
        total_ref = sample_count * per_ref
        total_creative = creative_count * per_creative
        total = total_ref + total_creative + creative_prompts_sparks + assessment_sparks

        return {
            "breakdown": {
                "generate_per_image": generate_sparks,
                "describe_per_image": describe_sparks,
                "embed_per_image": embed_sparks,
                "vision_eval_per_image": vision_eval_sparks,
                "creative_prompts": creative_prompts_sparks,
                "assessment": assessment_sparks,
                "per_reference_pair": per_ref,
                "per_creative_pair": per_creative,
            },
            "totals": {
                "reference": total_ref,
                "creative": total_creative,
                "overhead": creative_prompts_sparks + assessment_sparks,
                "total": total,
            },
            "params": {
                "base_model": base_model,
                "sample_count": sample_count,
                "creative_count": creative_count,
            },
            "providers": {
                "generation": f"{gen_provider}/{gen_model}",
                "vision": f"{vision_prov}/{vision_model}",
                "evaluation": f"{eval_prov}/{eval_model}",
                "embedding": "openai/text-embedding-3-small",
            },
        }

    @staticmethod
    def get_summarize_costs(
        db: Session,
        user_id: int,
        cluster_count: int = 1,
    ) -> dict:
        """Estimate cluster summarization costs."""
        from app.services.settings_service import SettingsService
        from app.services.token_estimator import estimate_prompt_tokens

        settings = SettingsService(db, user_id)
        provider_config = settings.get_provider_config()

        lang_provider = provider_config.get("language_provider", "openai")
        if lang_provider == "openai":
            lang_model = provider_config.get("openai_language_model", "gpt-4o-mini")
        elif lang_provider == "anthropic":
            lang_model = provider_config.get("anthropic_language_model", "claude-sonnet-4-20250514")
        else:
            lang_model = provider_config.get("fal_language_model", "x-ai/grok-2-vision-1212")

        # Try DB averages for tokens
        avg_in, avg_out = BillingService.get_average_tokens(
            db, lang_provider, lang_model, "summarize",
        )
        # Fallback: ~3500 chars input (~815 tokens), 500 output tokens
        input_tokens = avg_in if avg_in is not None else estimate_prompt_tokens("x" * 3500)
        output_tokens = avg_out if avg_out is not None else 500

        per_cluster, _ = _estimate_sparks(
            db, lang_provider, lang_model, "summarize",
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens,
        )
        total = per_cluster * cluster_count

        return {
            "per_cluster": per_cluster,
            "cluster_count": cluster_count,
            "total": total,
            "provider": f"{lang_provider}/{lang_model}",
            "estimated_input_tokens": input_tokens,
            "estimated_output_tokens": output_tokens,
        }

    # --- Output token averages for cost estimation ---

    @staticmethod
    def get_average_tokens(
        db: Session, provider: str, model: str, operation: str, min_samples: int = 3
    ) -> tuple[int | None, int | None]:
        """Query AVG(input_tokens) and AVG(output_tokens) from usage_records.

        Returns (avg_input, avg_output). Either value is None if fewer than
        min_samples records exist with non-null values for that column.
        """
        row = (
            db.query(
                func.count(UsageRecord.id).label("cnt"),
                func.avg(UsageRecord.input_tokens).label("avg_in"),
                func.avg(UsageRecord.output_tokens).label("avg_out"),
            )
            .filter(
                UsageRecord.provider == provider,
                UsageRecord.model == model,
                UsageRecord.operation == operation,
            )
            .first()
        )
        if not row or row.cnt < min_samples:
            logger.debug(
                "DB_AVG | %s/%s %s | samples=%d (need %d) → using formula fallback",
                provider, model, operation, row.cnt if row else 0, min_samples,
            )
            return None, None

        avg_in = int(row.avg_in) if row.avg_in is not None else None
        avg_out = int(row.avg_out) if row.avg_out is not None else None
        logger.debug(
            "DB_AVG | %s/%s %s | samples=%d | avg_in=%s avg_out=%s",
            provider, model, operation, row.cnt, avg_in, avg_out,
        )
        return avg_in, avg_out

    @staticmethod
    def get_average_output_tokens(
        db: Session, provider: str, model: str, operation: str, min_samples: int = 3
    ) -> int | None:
        """Query AVG(output_tokens) from usage_records for a provider/model/operation.

        Returns None if fewer than min_samples records exist, so caller can
        fall back to defaults in token_estimator.py.
        """
        _, avg_out = BillingService.get_average_tokens(
            db, provider, model, operation, min_samples
        )
        return avg_out

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
        spent_map = {r.user_id: {"total_spent": int((r.total_spent or 0) * USD_TO_SPARKS), "last_activity": r.last_activity} for r in spent_query}

        output = []
        for user, balance in results:
            spent_info = spent_map.get(user.id, {"total_spent": 0, "last_activity": None})
            output.append({
                "user_id": user.id,
                "email": user.email,
                "display_name": user.display_name,
                "balance": balance.balance_sparks if balance else 0,
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
        total_charged = 0
        by_provider: dict[str, int] = {}
        by_operation: dict[str, int] = {}

        for r in records:
            total_raw += r.raw_cost
            sparks = r.delta_sparks if r.delta_sparks is not None else int(r.charged_cost * USD_TO_SPARKS)
            total_charged += sparks
            by_provider[r.provider] = by_provider.get(r.provider, 0) + sparks
            by_operation[r.operation] = by_operation.get(r.operation, 0) + sparks

        return {
            "total_raw_cost": float(total_raw),
            "total_charged": total_charged,
            "margin": float(Decimal(str(total_charged)) / USD_TO_SPARKS - total_raw),
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
    provider_cost: float | None = None,
    defer_debit: bool = False,
) -> None:
    """Record usage in its own session. Called from write_log after-hook."""
    from app.services.billing_context import set_last_usage_record_id

    db = SessionLocal()
    try:
        svc = BillingService(db, user_id)
        record = svc.record_usage(
            operation=operation,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pipeline_log_id=pipeline_log_id,
            provider_cost=provider_cost,
            defer_debit=defer_debit,
        )
        # Ensure the UsageRecord is committed even when charged_cost=0
        # or defer_debit=True (record_usage only commits via debit_usage
        # when cost > 0 and not deferred).
        db.commit()
        # Store record ID in thread-local context so callers (e.g. vision API)
        # can deterministically look up the cost without race conditions.
        set_last_usage_record_id(record.id)
    except Exception as e:
        logger.warning(f"Failed to record usage for user {user_id}: {e}")
        db.rollback()
    finally:
        db.close()


def finalize_job_billing(
    db: Session,
    user_id: int,
    job_id: int | None,
    description: str | None = None,
    create_debit: bool = False,
) -> Decimal:
    """Aggregate usage records for a job and set Job.charged_cost.

    Looks up all UsageRecords linked to this job's pipeline logs, sums the
    charged_cost, and sets job.charged_cost.

    When create_debit=True (deferred pipeline billing), also creates ONE
    combined BalanceTransaction debit. For non-deferred tasks (generate, edit,
    train, evaluate), debits already happened inline so only the aggregation
    to Job.charged_cost is needed.

    Returns total sparks charged.
    """
    if not job_id:
        return Decimal("0")

    from app.models.job import Job
    from app.models.pipeline_log import PipelineLog

    # Find usage records linked to this job via pipeline_log_id → pipeline_logs.job_id
    usage_records_legacy = (
        db.query(UsageRecord)
        .join(PipelineLog, UsageRecord.pipeline_log_id == PipelineLog.id)
        .filter(PipelineLog.job_id == job_id, UsageRecord.user_id == user_id)
        .order_by(UsageRecord.created_at)
        .all()
    )

    # Orchestrator path: UsageRecords linked via cost_decision_id → CostDecision.job_id
    usage_records_orch: list[UsageRecord] = []
    try:
        from app.models.cost_decision import CostDecision
        usage_records_orch = (
            db.query(UsageRecord)
            .join(CostDecision, UsageRecord.cost_decision_id == CostDecision.id)
            .filter(CostDecision.job_id == job_id, UsageRecord.user_id == user_id)
            .order_by(UsageRecord.created_at)
            .all()
        )
    except Exception:
        pass  # Table may not exist yet during migration transition

    # Deduplicate by ID and combine
    seen_ids: set[int] = set()
    usage_records: list[UsageRecord] = []
    for r in usage_records_legacy + usage_records_orch:
        if r.id not in seen_ids:
            seen_ids.add(r.id)
            usage_records.append(r)
    usage_records.sort(key=lambda r: r.created_at)

    if not usage_records:
        # Still set charged_cost to 0 so it's not NULL
        job = db.query(Job).filter(Job.id == job_id).first()
        if job and job.charged_cost is None:
            job.charged_cost = Decimal("0")
            job.charged_sparks = 0
            db.commit()
        return Decimal("0")

    total_charged = sum((r.charged_cost for r in usage_records), Decimal("0"))
    total_sparks = total_charged * USD_TO_SPARKS

    # Build breakdown: "tag: 1.5 + describe: 4.2 + embed: 0.02"
    breakdown_parts = []
    for r in usage_records:
        sparks = r.charged_cost * USD_TO_SPARKS
        breakdown_parts.append(f"{r.operation}: {float(sparks):.2f}")
    breakdown = " + ".join(breakdown_parts)

    # Create ONE combined debit transaction (only for deferred billing)
    if create_debit and total_sparks > 0:
        desc = description or f"Pipeline ({breakdown} sparks)"
        svc = BillingService(db, user_id)
        svc.debit_usage(
            amount=total_sparks,
            description=desc,
        )

    # Set job.charged_cost + charged_sparks (dual-write)
    job = db.query(Job).filter(Job.id == job_id).first()
    if job:
        job.charged_cost = total_sparks
        job.charged_sparks = int(total_sparks)
        db.commit()

    logger.info(
        "BILLING FINALIZE | user_id=%s job=%s sparks=%.2f debit=%s breakdown=[%s]",
        user_id, job_id, float(total_sparks), create_debit, breakdown,
    )

    return total_sparks


# Keep old name as alias for backward compatibility
finalize_pipeline_billing = finalize_job_billing
