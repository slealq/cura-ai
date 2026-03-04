"""``billable`` context manager — the enforced-only path for provider calls.

Usage::

    with billable(db, user_id, operation="generate", provider="fal",
                  model="flux-dev", ...) as b:
        # Option A (preferred): decorator wraps the call
        result = b.call(generator.generate, prompt=prompt, params=params)

        # Option B (escape hatch): caller manages the call
        result = provider.generate_image(...)
        b.set_actual(input_tokens=..., output_tokens=..., provider_cost=...)

``b.call()`` automatically:
  1. Invokes the provider function
  2. Extracts token counts / provider cost from billing context vars
  3. Calls ``record_actual()`` on the orchestrator
  4. On provider exception → ``fail_decision()`` automatically

If neither ``call()`` nor ``set_actual()`` is used, the context manager
falls back to the ContextVar token bridge with a deprecation warning
(migration mode) or raises ``MissingActualError`` (enforcement mode).

Cancellation is handled via ``b.cancel()`` inside the ``with`` block.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.billing_context import (
    clear_last_api_call_tokens,
    get_last_api_call_tokens,
    get_trace_id,
    is_billing_deferred,
    make_idempotency_key,
)
from app.services.billing_orchestrator import (
    ORCHESTRATOR_ENABLED_OPS,
    BillingOrchestrator,
)

logger = logging.getLogger(__name__)


class MissingActualError(Exception):
    """Raised in enforcement mode when no actual was recorded."""
    pass


class _BillableContext:
    """Internal state holder for a single billable operation."""

    def __init__(
        self,
        orch: BillingOrchestrator | None,
        decision_id: int | None,
        is_new: bool,
        *,
        defer_debit: bool | None,
    ):
        self.orch = orch
        self.decision_id = decision_id
        self.is_new = is_new
        self._defer_debit = defer_debit
        self._actual_recorded = False
        self._cancelled = False
        self._failed = False

    @property
    def skipped(self) -> bool:
        """True if the decision was an idempotent duplicate — caller should skip."""
        return not self.is_new

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Invoke a provider function and automatically record billing actuals.

        On success: extracts tokens from ContextVar bridge and records actual.
        On exception: calls fail_decision and re-raises.
        """
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            if self.orch and self.decision_id:
                self.orch.fail_decision(self.decision_id, str(exc))
                self._failed = True
            raise

        self._record_from_context()
        return result

    def set_actual(
        self,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        provider_cost: float | None = None,
        response_snapshot: dict | None = None,
    ) -> None:
        """Explicitly record actual billing values (escape hatch)."""
        if not self.orch or not self.decision_id:
            return
        if self._actual_recorded:
            return

        defer = self._resolve_defer()
        self.orch.record_actual(
            self.decision_id,
            actual_input_tokens=input_tokens,
            actual_output_tokens=output_tokens,
            provider_cost=provider_cost,
            defer_debit=defer,
            response_snapshot=response_snapshot,
        )
        self._actual_recorded = True

    def cancel(self) -> None:
        """Cancel the billing decision (e.g. user-initiated cancellation)."""
        if self.orch and self.decision_id and not self._cancelled:
            self.orch.cancel_decision(self.decision_id)
            self._cancelled = True

    def fail(self, error: str) -> None:
        """Explicitly fail the billing decision."""
        if self.orch and self.decision_id and not self._failed:
            self.orch.fail_decision(self.decision_id, error)
            self._failed = True

    # --- Internal helpers ---

    def _record_from_context(self, response_snapshot: dict | None = None) -> None:
        """Extract tokens from ContextVar bridge and record actual."""
        if not self.orch or not self.decision_id:
            return
        if self._actual_recorded:
            return

        in_tok, out_tok, prov_cost = get_last_api_call_tokens()
        clear_last_api_call_tokens()

        defer = self._resolve_defer()
        self.orch.record_actual(
            self.decision_id,
            actual_input_tokens=in_tok,
            actual_output_tokens=out_tok,
            provider_cost=prov_cost,
            defer_debit=defer,
            response_snapshot=response_snapshot,
        )
        self._actual_recorded = True

    def _resolve_defer(self) -> bool:
        """Resolve whether to defer debit."""
        if self._defer_debit is not None:
            return self._defer_debit
        return is_billing_deferred()

    def _on_exit(self) -> None:
        """Called when exiting the ``with`` block.

        In migration mode: falls back to ContextVar bridge with a warning.
        In enforcement mode: would raise MissingActualError.
        """
        if self._actual_recorded or self._cancelled or self._failed:
            return
        if not self.orch or not self.decision_id:
            return
        if not self.is_new:
            return  # skipped duplicate — no actual expected

        # Migration mode fallback: try ContextVar bridge
        in_tok, out_tok, prov_cost = get_last_api_call_tokens()
        if in_tok is not None or out_tok is not None or prov_cost is not None:
            logger.warning(
                "BILLING DEPRECATION | decision=%s — actual recorded via ContextVar fallback. "
                "Use billable.call() or billable.set_actual() instead.",
                self.decision_id,
            )
            self._record_from_context()
        else:
            # No actual available at all — log warning (migration mode)
            logger.warning(
                "BILLING MISSING_ACTUAL | decision=%s — no actual recorded. "
                "Provider call may have been skipped or tokens lost.",
                self.decision_id,
            )


@contextmanager
def billable(
    db: Session,
    user_id: int,
    operation: str,
    provider: str,
    model: str,
    *,
    # Idempotency
    idempotency_key: str | None = None,
    resource_id: int | None = None,
    # Context for estimation
    image_id: int | None = None,
    job_id: int | None = None,
    trace_id: str | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    prompt_text: str | None = None,
    tags: list[str] | None = None,
    description: str | None = None,
    with_lora: bool = False,
    generation_params: dict | None = None,
    request_snapshot: dict | None = None,
    # Settlement
    defer_debit: bool | None = None,
):
    """Context manager for billable provider calls.

    Yields a ``_BillableContext`` object with ``.call()``, ``.set_actual()``,
    ``.cancel()``, ``.fail()``, and ``.skipped`` methods/properties.

    If the operation is not in ``ORCHESTRATOR_ENABLED_OPS``, yields a no-op
    context (all methods are safe to call but do nothing).
    """
    if operation not in ORCHESTRATOR_ENABLED_OPS:
        yield _BillableContext(orch=None, decision_id=None, is_new=True, defer_debit=defer_debit)
        return

    orch = BillingOrchestrator(db, user_id)

    # Auto-generate idempotency key if not provided
    if idempotency_key is None and resource_id is not None:
        idempotency_key = make_idempotency_key(
            user_id, trace_id or get_trace_id(), operation, resource_id,
        )

    decision, is_new = orch.create_decision(
        operation=operation,
        provider=provider,
        model=model,
        trace_id=trace_id or get_trace_id(),
        idempotency_key=idempotency_key,
        image_id=image_id,
        job_id=job_id,
        resource_id=resource_id,
        request_snapshot=request_snapshot,
        image_width=image_width,
        image_height=image_height,
        prompt_text=prompt_text,
        tags=tags,
        description=description,
        with_lora=with_lora,
        generation_params=generation_params,
    )

    ctx = _BillableContext(
        orch=orch,
        decision_id=decision.id,
        is_new=is_new,
        defer_debit=defer_debit,
    )
    try:
        yield ctx
    finally:
        ctx._on_exit()
