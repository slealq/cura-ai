"""BillingOrchestrator: explicit billing lifecycle for provider calls.

Every billable operation gets a CostDecision record BEFORE the provider call,
with full request/response snapshots for end-to-end traceability.
"""
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.billing import UsageRecord
from app.models.cost_decision import CostDecision, DecisionStatus
from app.services.billing_service import BillingService, InsufficientBalanceError, ZeroCostEstimateError
from app.services.cost_calculator import (
    USD_TO_SPARKS,
    calculate_cost,
    estimate_operation_tokens,
    get_catalog_entry,
    resolve_catalog_model,
)

logger = logging.getLogger(__name__)

# Operations managed by the orchestrator. When an operation is in this set,
# write_log() skips record_usage_standalone() and the task code uses the
# orchestrator instead.
ORCHESTRATOR_ENABLED_OPS: set[str] = {
    "tag", "describe", "embed",
    "generate", "edit",
    "train", "evaluate", "summarize", "expand_prompt",
}


class BillingOrchestrator:
    """Manages the billing lifecycle for a single user's operations."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id

    def create_decision(
        self,
        operation: str,
        provider: str,
        model: str,
        trace_id: str | None = None,
        idempotency_key: str | None = None,
        image_id: int | None = None,
        job_id: int | None = None,
        resource_id: int | None = None,
        request_snapshot: dict | None = None,
        estimated_input_tokens: int | None = None,
        estimated_output_tokens: int | None = None,
        # Context for auto-resolution and token estimation
        image_width: int | None = None,
        image_height: int | None = None,
        prompt_text: str | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
        with_lora: bool = False,
        generation_params: dict | None = None,
    ) -> tuple[CostDecision, bool]:
        """Create a billing decision before a provider call.

        Returns (decision, is_new). If is_new is False, the caller should
        skip the provider call (idempotent duplicate).
        """
        # Check existing by idempotency_key
        if idempotency_key:
            existing = (
                self.db.query(CostDecision)
                .filter(CostDecision.idempotency_key == idempotency_key)
                .first()
            )
            if existing and existing.status in (
                DecisionStatus.EXECUTED.value,
                DecisionStatus.CHARGED.value,
            ):
                logger.info(
                    "ORCH duplicate | key=%s status=%s — skipping",
                    idempotency_key, existing.status,
                )
                return existing, False

        # Resolve short model names → full catalog names
        provider, model, operation = resolve_catalog_model(
            provider, model, operation, with_lora=with_lora,
        )

        # Auto-estimate tokens when caller didn't provide them
        if estimated_input_tokens is None and estimated_output_tokens is None:
            est_in, est_out = estimate_operation_tokens(
                provider, model, operation,
                image_width=image_width,
                image_height=image_height,
                prompt_text=prompt_text,
                tags=tags,
                description=description,
            )
            if est_in is not None:
                estimated_input_tokens = est_in
            if est_out is not None:
                estimated_output_tokens = est_out

        # Snapshot catalog pricing at decision time
        entry, match_tier = get_catalog_entry(self.db, provider, model, operation)

        # Estimate cost via the shared estimate_sparks() function
        cost_per_input = None
        cost_per_output = None
        cost_per_call_val = None
        markup = None
        billing_model = None

        if entry:
            cost_per_input = entry.cost_per_input_token
            cost_per_output = entry.cost_per_output_token
            cost_per_call_val = entry.cost_per_call
            markup = entry.platform_markup
            billing_model = "per_call" if (entry.cost_per_call and entry.cost_per_call > 0) else "per_token"

        from app.services.cost_calculator import estimate_sparks as _est

        estimated_sparks, _ = _est(
            self.db, provider, model, operation,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            generation_params=generation_params,
        )

        decision = CostDecision(
            trace_id=trace_id,
            user_id=self.user_id,
            job_id=job_id,
            operation=operation,
            provider=provider,
            model=model,
            catalog_entry_id=entry.id if entry else None,
            catalog_match_tier=match_tier,
            estimated_input_tokens=estimated_input_tokens,
            estimated_output_tokens=estimated_output_tokens,
            estimated_sparks=estimated_sparks,
            cost_per_input_token=cost_per_input,
            cost_per_output_token=cost_per_output,
            cost_per_call=cost_per_call_val,
            platform_markup=markup,
            billing_model=billing_model,
            image_id=image_id,
            resource_id=resource_id,
            request_snapshot=request_snapshot,
            status=DecisionStatus.PENDING.value,
            idempotency_key=idempotency_key,
        )
        self.db.add(decision)
        self.db.flush()

        # Pre-guard: abort if estimated cost is zero (broken billing config)
        if estimated_sparks is None or estimated_sparks <= 0:
            no_catalog = entry is None
            if no_catalog:
                err = f"No catalog entry for {provider}/{model}/{operation}"
            else:
                err = f"Catalog entry exists but computed 0 sparks for {provider}/{model}/{operation}"
            decision.status = DecisionStatus.FAILED.value
            decision.error_message = f"Zero-cost estimate: {err}"
            self.db.commit()
            logger.error(
                "ORCH zero-estimate | id=%s op=%s %s/%s — %s",
                decision.id, operation, provider, model, err,
            )
            raise ZeroCostEstimateError(err)

        # Reserve estimated sparks to prevent concurrent overspend
        reserved = 0
        if estimated_sparks and estimated_sparks > 0:
            svc = BillingService(self.db, self.user_id)
            if not svc.reserve_sparks(estimated_sparks, decision.id):
                decision.status = DecisionStatus.FAILED.value
                decision.error_message = "Insufficient balance for reservation"
                self.db.commit()
                raise InsufficientBalanceError(
                    f"User {self.user_id} has insufficient credits "
                    f"(need ~{estimated_sparks} sparks)"
                )
            reserved = estimated_sparks

        decision.reserved_sparks = reserved
        self.db.commit()

        logger.info(
            "ORCH decision | id=%s op=%s %s/%s trace=%s est_sparks=%s reserved=%s",
            decision.id, operation, provider, model, trace_id, estimated_sparks, reserved,
        )

        return decision, True

    def record_actual(
        self,
        decision_id: int,
        actual_input_tokens: int | None = None,
        actual_output_tokens: int | None = None,
        provider_cost: float | None = None,
        response_snapshot: dict | None = None,
        defer_debit: bool = False,
        pipeline_log_id: int | None = None,
        provider_request_id: str | None = None,
    ) -> UsageRecord:
        """Record actual cost after a provider call completes.

        Creates a UsageRecord, optionally debits balance, and updates
        the decision status.
        """
        decision = self.db.query(CostDecision).filter(CostDecision.id == decision_id).first()
        if not decision:
            raise ValueError(f"CostDecision {decision_id} not found")

        # Calculate actual cost
        raw_cost, charged_cost, detail = calculate_cost(
            self.db,
            decision.provider,
            decision.model,
            decision.operation,
            actual_input_tokens,
            actual_output_tokens,
            provider_cost=provider_cost,
        )

        sparks = int(charged_cost * USD_TO_SPARKS)

        # Post-guard: log ERROR if actual cost resolved to zero (provider already called)
        if sparks <= 0:
            logger.error(
                "ORCH zero-actual | decision=%s op=%s %s/%s "
                "in_tok=%s out_tok=%s provider_cost=%s raw=%s charged=%s — "
                "billing config may be broken",
                decision_id, decision.operation, decision.provider, decision.model,
                actual_input_tokens, actual_output_tokens, provider_cost,
                raw_cost, charged_cost,
            )
            decision.error_message = (
                f"Zero actual sparks: in_tok={actual_input_tokens} out_tok={actual_output_tokens} "
                f"provider_cost={provider_cost} raw={raw_cost} charged={charged_cost}"
            )

        from app.services.billing_context import get_trace_id

        record = UsageRecord(
            user_id=self.user_id,
            pipeline_log_id=pipeline_log_id,
            operation=decision.operation,
            provider=decision.provider,
            model=decision.model,
            input_tokens=actual_input_tokens,
            output_tokens=actual_output_tokens,
            raw_cost=raw_cost,
            charged_cost=charged_cost,
            detail=detail,
            trace_id=get_trace_id(),
            cost_decision_id=decision_id,
            provider_request_id=provider_request_id,
            delta_sparks=sparks,
            delta_reason="actual",
        )
        self.db.add(record)
        self.db.flush()

        # Update decision
        decision.response_snapshot = response_snapshot
        decision.updated_at = datetime.utcnow()

        reserved = decision.reserved_sparks or 0
        svc = BillingService(self.db, self.user_id)

        if charged_cost > 0 and not defer_debit:
            spark_amount = charged_cost * USD_TO_SPARKS
            svc.release_and_debit(
                reserved_amount=reserved,
                actual_amount=spark_amount,
                description=f"{decision.operation} via {decision.provider}/{decision.model}",
                usage_record_id=record.id,
            )
            decision.reserved_sparks = 0
            decision.status = DecisionStatus.CHARGED.value
        else:
            # Deferred debit or zero cost — just release the reservation
            if reserved > 0:
                svc.release_reservation(reserved)
                decision.reserved_sparks = 0
            decision.status = DecisionStatus.EXECUTED.value

        self.db.commit()

        logger.info(
            "ORCH actual | decision=%s op=%s sparks=%s debit=%s",
            decision_id, decision.operation, sparks, not defer_debit,
        )

        return record

    def fail_decision(self, decision_id: int, error_message: str) -> None:
        """Mark a decision as failed and release any reservation."""
        decision = self.db.query(CostDecision).filter(CostDecision.id == decision_id).first()
        if decision:
            reserved = decision.reserved_sparks or 0
            if reserved > 0:
                svc = BillingService(self.db, self.user_id)
                svc.release_reservation(reserved)
                decision.reserved_sparks = 0
            decision.status = DecisionStatus.FAILED.value
            decision.error_message = error_message
            decision.updated_at = datetime.utcnow()
            self.db.commit()

    def cancel_decision(self, decision_id: int) -> None:
        """Mark a decision as cancelled and release any reservation."""
        decision = self.db.query(CostDecision).filter(CostDecision.id == decision_id).first()
        if decision:
            reserved = decision.reserved_sparks or 0
            if reserved > 0:
                svc = BillingService(self.db, self.user_id)
                svc.release_reservation(reserved)
                decision.reserved_sparks = 0
            decision.status = DecisionStatus.CANCELLED.value
            decision.updated_at = datetime.utcnow()
            self.db.commit()
