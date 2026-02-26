# Billing & Cost Architecture Review

## Executive Summary

The billing system is functional and covers the core needs: CostCatalog pricing, UsageRecord tracking, UserBalance management with row-level locking, and both inline and deferred billing paths. However, **the system was grown organically and lacks a unified "decision → execute → reconcile" model**, making it hard to answer the question: *"What did we estimate, what did we charge, and why?"*

**Top concerns:**
1. **Estimate and actual are computed by entirely separate code paths** — the estimate endpoint uses `token_estimator.py` + catalog lookup, while the actual flows through `log_service.py` → `billing_service.py` with no link between them.
2. **No correlation between estimate and charge** — there is no `cost_decision_id` or `request_id` that ties a preflight quote to the subsequent provider call and debit.
3. **Billed operations must never auto-retry** — inline-billed tasks (tag, describe, embed, generate, edit, evaluate) can be retried by Celery, which re-runs the provider call (external cost we pay) AND internal billing (cost we charge the user). Worse: if all retries fail, we've paid the provider N times but have nothing to deliver — we can't charge the user. The only safe policy: **fail explicitly, let the user manually retry.** Idempotency keys are defense-in-depth, not the primary mechanism.
4. **Race-prone cost attribution in vision API** — `_get_latest_charged_cost()` queries the most recent UsageRecord by `(user_id, provider, model, operation)` to find the cost of the call it just made. Under concurrent requests, this can pick up a different request's cost.
5. **TOCTOU gap in balance check** — `check_balance_or_raise()` is a point-in-time snapshot. Concurrent operations can drive the balance negative between check and debit. No atomic guard.
6. **Silent $0 charges on catalog miss** — when `_get_catalog_entry()` returns None, the system logs a WARNING but charges $0. No alert, no blocked operation. A new model or renamed operation silently runs for free.
7. **`finalize_job_billing()` not in `finally` block for batch tasks** — `batch_generate` and `batch_edit` call finalize on the success path only. If the parent task crashes, `Job.charged_cost` is never set even though child tasks already debited inline.
8. **Billing failure silently swallowed** — `write_log()` catches billing exceptions at line 86-87 with `logger.warning()`. Provider call succeeds, PipelineLog created, but UsageRecord may silently fail. The user used the API but wasn't charged.

**Estimated effort to reach a debuggable state (Phase 0):** ~2 weeks of focused work. Full refactor through Phase 3: ~6-8 weeks incremental.

---

## 1. REPO MAP — Billing & Cost Paths

### 1.1 File Inventory

| Layer | File | Role |
|-------|------|------|
| **DB Models** | `backend/app/models/billing.py` | CostCatalog, UsageRecord, UserBalance, BalanceTransaction |
| **DB Models** | `backend/app/models/job.py` | Job.charged_cost field |
| **DB Models** | `backend/app/models/vision_result.py` | VisionResult.charged_cost field |
| **DB Models** | `backend/app/models/pipeline_log.py` | PipelineLog (links UsageRecord to tasks) |
| **Service** | `backend/app/services/billing_service.py` | Core billing: cost calc, catalog lookup, record_usage, debit, finalize |
| **Service** | `backend/app/services/billing_context.py` | Thread-local context (user_id, job_id, image_id, deferred flag) |
| **Service** | `backend/app/services/token_estimator.py` | Formula-based token estimation for cost previews |
| **Service** | `backend/app/services/log_service.py` | write_log() — hook that triggers record_usage_standalone() |
| **Service** | `backend/app/services/vision_service.py` | VisionResult CRUD (stores charged_cost) |
| **API** | `backend/app/api/billing.py` | 18 endpoints: balance, transactions, usage, estimates, admin CRUD |
| **API** | `backend/app/api/vision.py` | Vision analyze endpoint — triggers billing inline |
| **Workers** | `backend/app/workers/tasks.py` | Pipeline tasks: tag, describe, embed, cluster, batch ops |
| **Workers** | `backend/app/workers/generation_tasks.py` | Generation tasks: train, generate, edit, evaluate |
| **Providers** | `backend/app/providers/openai_provider.py` | OpenAI calls — returns token counts |
| **Providers** | `backend/app/providers/anthropic_provider.py` | Anthropic calls — returns token counts |
| **Providers** | `backend/app/providers/fal_provider.py` | fal.ai calls — returns provider_cost USD |
| **Providers** | `backend/app/providers/fal_vision_provider.py` | fal.ai OpenRouter vision — returns tokens + cost |
| **Migrations** | `backend/migrations/versions/029-040` | Billing schema evolution |

### 1.2 Call Graph: Billing Flow

```
HTTP Request / Celery Task
  │
  ├── [Estimate Path - DISCONNECTED]
  │     billing.py endpoint
  │       → token_estimator.estimate_*()
  │       → BillingService._get_catalog_entry()
  │       → Return sparks to frontend (no persistence)
  │
  └── [Actual Charge Path]
        Provider call (OpenAI/Anthropic/fal.ai)
          → Provider extracts tokens or cost from response
          → Provider calls write_log(category=API_CALL, success=True, ...)
              │
              └── log_service.py:write_log()
                    ├── Creates PipelineLog entry (own SessionLocal)
                    └── If API_CALL + success:
                          record_usage_standalone() (ANOTHER SessionLocal)
                            │
                            └── billing_service.py:record_usage()
                                  ├── _calculate_cost()
                                  │     ├── _get_catalog_entry() [3-tier lookup]
                                  │     ├── If provider_cost: raw=provider_cost, charged=raw*markup
                                  │     └── If tokens: raw=in*rate+out*rate+call, charged=raw*markup
                                  ├── Create UsageRecord (with detail JSON)
                                  └── If !defer_debit && charged>0:
                                        debit_usage()
                                          ├── SELECT FOR UPDATE on UserBalance
                                          ├── balance -= sparks
                                          └── Create BalanceTransaction(DEBIT)

        [Job Finalization - called by task code]
        finalize_job_billing()
          ├── Query UsageRecords via PipelineLog.job_id
          ├── Sum charged_cost across records
          ├── If create_debit: ONE combined BalanceTransaction
          └── Set Job.charged_cost = total_sparks
```

**Critical design issue:** Billing is triggered as a **side-effect** of `write_log()`. The provider adapter calls `write_log()` which then triggers `record_usage_standalone()`. This means the billing trigger is embedded inside the logging path — you can't control decision/execution/reconcile because billing happens passively, not as an explicit orchestrated step.

### 1.3 Feature-by-Feature Billing Table

| Feature | Endpoint/Task | Cost Inputs | Catalog Lookup | Estimate Location | Actual Location | Usage Recorded | Balance Debited | Correlation IDs |
|---------|--------------|-------------|----------------|-------------------|-----------------|----------------|-----------------|-----------------|
| **Vision (tag/describe)** | `POST /vision/analyze` | provider, model, image dims, prompt | `_get_catalog_entry(provider, model, "tag"/"describe")` | `GET/POST /billing/vision-costs` via token_estimator | `log_service.write_log()` → `record_usage_standalone()` | UsageRecord + VisionResult.charged_cost | Inline (immediate) | user_id, pipeline_log_id; **NO job_id** |
| **Embed** | `embed_image` task | model, tag+desc text length | `_get_catalog_entry("openai", "text-embedding-3-small", "embed")` | Part of vision-costs "embed" field | `write_log()` → `record_usage_standalone()` | UsageRecord | Deferred (in pipeline) or Inline | user_id, image_id, job_id, pipeline_log_id |
| **Full Pipeline** | `process_image_pipeline` task | provider, model, image dims | N/A (composite) | `POST /billing/vision-costs` (per-image × count) | 3 separate `record_usage()` calls (tag+describe+embed) | 3 UsageRecords | Deferred → ONE finalize debit | user_id, image_id, job_id |
| **Generate** | `generate_image` task | base_model, loras, resolution, steps | `_get_catalog_entry("fal", fal_model, "generate")` | `GET /billing/generation-costs` (catalog cost_per_call) | `write_log(provider_cost=fal_cost)` | UsageRecord | Inline | user_id, job_id, pipeline_log_id |
| **Edit** | `edit_image` task | edit_model, resolution | `_get_catalog_entry("fal", fal_model, "edit")` | `GET /billing/edit-costs` (catalog cost_per_call) | `write_log(provider_cost=fal_cost)` | UsageRecord | Inline | user_id, job_id, pipeline_log_id |
| **Train LoRA** | `train_lora` task | base_model, image_count, steps | `_get_catalog_entry("fal", trainer_model, "train")` | `GET /billing/training-costs` (catalog cost_per_call) | `write_log(provider_cost=fal_cost)` | UsageRecord | Inline | user_id, job_id, pipeline_log_id |
| **Evaluate LoRA** | `evaluate_lora` task | sample_count, creative_count, provider, model | Multiple lookups (generate + describe + embed + evaluate per pair) | **NONE** — no estimate endpoint exists | Multiple `write_log()` calls across pair types | Many UsageRecords | Inline (each call) | user_id, job_id |
| **Expand Prompt** | Inside `generate_image` task | prompt length | `_get_catalog_entry("openai", "gpt-4o-mini", "expand_prompt")` | Part of generation-costs response | `write_log()` | UsageRecord | Inline | user_id, job_id |
| **Cluster Summarize** | `summarize_cluster` task | cluster size, provider, model | `_get_catalog_entry(provider, model, "summarize")` | **NONE** | `write_log()` | UsageRecord | Inline | user_id; **NO job_id tagged** |
| **Batch Describe** | `run_batch_describe` task | provider, model, image_count | N/A (composite) | Frontend multiplies per-image cost × count | Deferred per-image `record_usage()` + `finalize_job_billing()` | N UsageRecords | Deferred → ONE finalize | user_id, job_id |

### 1.4 CostCatalog Matching Logic

```
_get_catalog_entry(provider, model, operation):

  Tier 1: SELECT WHERE provider=X AND model=Y AND operation=Z AND is_active
           → if found, return

  Tier 2: SELECT WHERE provider=X AND model="*" AND operation=Z AND is_active
           → if found, return

  Tier 3: SELECT WHERE provider=X AND model LIKE "%*%" AND operation=Z AND is_active
           → for each: if model_arg.startswith(wc.model.replace("*","")): return

  None → log WARNING "BILLING MISS", charge $0
```

**File:** `billing_service.py:285-333`

**Known ambiguity in Tier 3:** When multiple prefix wildcards match the same model (e.g., `"openrouter/*"` and `"openrouter/qwen*"` both match `"openrouter/qwen-vl-max"`), the current code returns whichever SQLAlchemy yields first — **no deterministic ordering**. This must be fixed to use "longest prefix wins" or a `priority` column on CostCatalog.

---

## 2. GAPS, BUG RISKS & ARCHITECTURAL SMELLS

### CORRECTNESS

#### C1. Race in `_get_latest_charged_cost()` (Severity: HIGH)
**File:** `backend/app/api/vision.py:91-110`

The vision endpoint calls the provider, then queries for the most recent UsageRecord to find what was charged:
```python
charged_cost = _get_latest_charged_cost(db, current_user.id, request.provider, result.model, "tag")
```
This queries `ORDER BY created_at DESC LIMIT 1`. Under concurrent requests from the same user with the same provider/model/operation, this can return a *different* request's cost. The correct approach is to capture the UsageRecord.id from the `record_usage()` call and use that directly.

**Impact:** VisionResult.charged_cost may be attributed to the wrong operation. Billing page shows wrong per-analysis costs.

#### C2. Billed operations must never auto-retry (Severity: CRITICAL)
**File:** `backend/app/workers/tasks.py` (tag_image, describe_image, embed_image, summarize_cluster), `backend/app/workers/generation_tasks.py` (generate_image, edit_image, evaluate_lora)

All inline-billed tasks use default Celery retry behavior. If Celery retries a task (worker crash, timeout, OOM), **both** the provider call AND the billing fire again:
- **External cost:** The provider (OpenAI, fal.ai, etc.) charges again for the duplicate API call. This is real money we pay that no internal fix can recover.
- **Internal cost:** `write_log()` creates a new PipelineLog, and `record_usage_standalone()` creates a new UsageRecord + debit. The user is charged twice.
- **Worst case:** All retries fail. We've paid the provider N times, the user received nothing, and we can't charge them. Pure loss.

`train_lora` is the ONLY task protected via `acks_late=False, max_retries=0`.

**Impact:** Provider charges us N times. User charged N times internally. If retries all fail: unrecoverable external cost with nothing to deliver.

**Primary fix: Disable retries for all billed tasks.**
```python
# Every task that calls a paid provider API:
@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def tag_image(self, ...):
    ...
```
This is the `train_lora` pattern, applied to all billed tasks. On failure: set Job status to FAILED, let the user decide whether to retry via the UI.

**Note on partial pipeline completion:** With `max_retries=0` on each sub-task, if `tag_image` succeeds but `describe_image` fails, the image has tags but no description. This is acceptable — the job is marked FAILED, and the user retries the whole pipeline. Partial results (tags) remain on the image and will be overwritten on retry.

**Defense-in-depth: Idempotency keys on CostDecision.**
Even with `max_retries=0`, edge cases exist (Celery visibility timeout, broker redelivery). CostDecision with a UNIQUE `idempotency_key` provides a second layer:
1. Create CostDecision **before** provider call
2. If key already exists with status `executed`/`charged` → skip provider call entirely
3. UNIQUE constraint on `cost_decisions.idempotency_key` prevents duplicates at the DB level

#### C3. `finalize_job_billing()` not in finally for batch tasks (Severity: MEDIUM)
**File:** `generation_tasks.py` — `batch_generate` (line ~767), `batch_edit` (line ~1090)

Child tasks bill inline (`from_batch=True` skips their own finalize). The parent calls `finalize_job_billing()` on the success path. If the parent crashes before reaching that line, `Job.charged_cost` remains NULL even though balance was already debited. This creates an accounting discrepancy.

**Impact:** Admin reporting sees NULL charged_cost for jobs where money was already taken.

#### C4. TOCTOU gap in balance check (Severity: HIGH)
**File:** `billing_service.py:71-79`

`check_balance_or_raise()` checks `balance > 0` but does not reserve funds. Between the check and the actual debit, concurrent operations can drive the balance negative. The row-level lock in `debit_usage()` only prevents concurrent *debits*, not the gap between check and debit.

**Impact:** User balance can go negative. This is an accounting invariant violation — once negative, the system has extended credit it didn't intend to.

**Fix (atomic debit guard — do this first, it's the simplest high-value fix):**
```python
def debit_usage_atomic(self, amount: Decimal, description: str, usage_record_id: int | None = None) -> BalanceTransaction | None:
    """Atomic debit: only succeeds if balance >= amount."""
    rows_updated = (
        self.db.query(UserBalance)
        .filter(UserBalance.user_id == self.user_id, UserBalance.balance >= amount)
        .update({UserBalance.balance: UserBalance.balance - amount})
    )
    if rows_updated == 0:
        return None  # Insufficient funds — caller decides whether to raise or proceed

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
```
This eliminates the TOCTOU gap entirely: the UPDATE only modifies the row if `balance >= amount`. No SELECT FOR UPDATE needed. If no row updated → insufficient funds.

**Long-term (Phase 2):** Balance reservation at decision time, settle after execution.

#### C5. Silent $0 on catalog miss (Severity: HIGH — revenue leakage + config drift)
**File:** `billing_service.py:231-238`

When no catalog entry matches, the system logs a WARNING and returns `(0, 0, None)`. The operation proceeds and completes successfully — the user gets a free API call. No admin notification, no blocked operation.

**Impact:** Adding a new provider model or renaming an operation causes silent revenue loss until someone notices the WARNING logs. This also hides config drift — you won't know that a model was renamed or a new provider added until you review logs.

**Fix: Explicit strict mode with anomaly recording.**

```python
# config
BILLING_STRICT_MODE = os.getenv("BILLING_STRICT_MODE", "true").lower() == "true"

# In _calculate_cost(), when entry is None:
if BILLING_STRICT_MODE:
    raise BillingCatalogMissError(
        f"No catalog entry for {provider}/{model}/{operation}. "
        "Add a CostCatalog entry or set BILLING_STRICT_MODE=false."
    )
else:
    # Non-strict: record anomaly for later review, proceed with cost=0
    self._record_billing_anomaly(
        anomaly_type="CATALOG_MISS",
        provider=provider, model=model, operation=operation,
        input_tokens=input_tokens, output_tokens=output_tokens,
    )
    return Decimal("0"), Decimal("0"), {"anomaly": "CATALOG_MISS", "provider": provider, "model": model, "operation": operation}
```

- `BILLING_STRICT_MODE=true` (default in prod): fail-closed, operation blocked
- `BILLING_STRICT_MODE=false` (dev/test): record `BillingAnomaly`, proceed with $0
- Store what was requested (provider/model/operation) in the anomaly so you can auto-create catalog rows later

#### C6. Billing failure silently swallowed in write_log() (Severity: HIGH)
**File:** `log_service.py:86-87`

```python
except Exception as usage_err:
    logger.warning(f"Failed to record usage: {usage_err}")
```

If `record_usage_standalone()` throws (DB connection failure, constraint violation, etc.), the exception is caught and logged as a WARNING. The provider call already succeeded. The PipelineLog already exists. But the UsageRecord doesn't — the user used the API without being charged.

**Impact:** "API succeeded, no charge" ghost operations. These are very hard to detect because there's no record of the missing charge — you'd need to cross-reference PipelineLogs that have no corresponding UsageRecord.

**Fix:** At minimum, mark the PipelineLog as `billing_failed=True` (new boolean column) so you can query for "successful API calls that failed to bill." Better: emit an error metric / alert on billing failure, not just a log warning.

### OBSERVABILITY

#### O1. No correlation between estimate and actual (Severity: HIGH)
There is no shared ID or object linking:
- The estimate shown in the DescribeAllDialog (`POST /billing/vision-costs`)
- The actual charges in UsageRecord

You cannot answer: "The user saw X sparks estimated, but was charged Y sparks. Why?"

#### O2. No request_id / idempotency_key on operations (Severity: HIGH)
There is no `request_id` or `correlation_id` that follows a user action from HTTP request → Celery task → provider call → UsageRecord → BalanceTransaction. Debugging requires manual timestamp correlation across logs and DB tables.

#### O3. PipelineLog cleanup destroys billing audit trail (Severity: MEDIUM)
**File:** `log_service.py:130-143`

`cleanup_old_logs(days=7)` deletes PipelineLogs older than 7 days. Since `UsageRecord.pipeline_log_id` is a **non-FK nullable int** (not a real foreign key), the UsageRecord survives but loses its link to the PipelineLog that recorded the actual token counts, duration, and success status.

**Impact:** After 7 days, you can see *what* was charged but not the operational context (which image, how long, what tokens the provider reported).

**Fix (recommended): Denormalize the minimal audit snapshot into UsageRecord** so PipelineLogs can be ephemeral:
- Add `context_json` to UsageRecord: `{image_id, task_name, duration_ms, success}` — copied from PipelineLog at billing time.
- Or: with CostDecision in place, store context there and stop relying on PipelineLog for billing audit entirely.
- Do NOT make `pipeline_log_id` a real FK — that would prevent cleanup and grow the table indefinitely. Instead, accept that PipelineLogs are ephemeral operational logs, and billing data must be self-contained.

#### O4. Estimate uses different code than actual (Severity: MEDIUM)
- **Estimate:** `token_estimator.py` formulas → catalog lookup in `billing.py` endpoints
- **Actual:** Provider response → `_calculate_cost()` in billing_service.py

The estimate formulas are completely disconnected from the actual cost path. There's no way to validate estimate accuracy without manually comparing.

#### O5. UsageRecord.detail lacks catalog entry ID (Severity: LOW)
The `detail` JSON stores rates and breakdown but not *which* CostCatalog row was matched (by ID or natural key). If the catalog is later updated, you can't reconstruct what rates were in effect at charge time. The frozen pricing snapshot in `detail` helps partially, but without the entry ID you can't trace *why* those rates were selected (exact vs wildcard match).

### MAINTAINABILITY

#### M1. Duplicated model maps (Severity: MEDIUM)
`BillingService.GENERATION_MODEL_MAP`, `EDIT_MODEL_MAP`, `TRAINING_MODEL_MAP` duplicate provider/model/operation tuples that also exist in the provider factory functions and the CostCatalog seed data. Adding a new model requires changes in 3+ places.

#### M2. Two separate DB sessions for log + billing (Severity: MEDIUM)
**File:** `log_service.py:32`, `billing_service.py:675`

`write_log()` opens its own `SessionLocal()`, then `record_usage_standalone()` opens another `SessionLocal()`. These are separate transactions — if the billing write fails (line 86-87: `logger.warning`), the PipelineLog still exists but has no corresponding UsageRecord. The billing failure is swallowed (see C6).

**Impact:** Provider call succeeds, PipelineLog created, but UsageRecord may silently fail. The user used the API but wasn't charged.

#### M3. `charged_cost` stored in different units across tables (Severity: MEDIUM)
- `UsageRecord.charged_cost`: **USD**
- `UserBalance.balance`: **sparks**
- `BalanceTransaction.amount`: **sparks**
- `Job.charged_cost`: **sparks** (set by `finalize_job_billing`)
- `VisionResult.charged_cost`: **USD** (set as `_get_latest_charged_cost().charged_cost`)

The mixed units are a maintenance footgun that will cause bugs as the codebase grows. Code must remember to multiply by `USD_TO_SPARKS` in some places but not others. A developer reading `Job.charged_cost = 12.5` can't tell if that's $12.50 or 12.5 sparks ($0.0125) without tracing the code path.

**Fix (do early, before more code is built on top):** Standardize to **sparks as integers everywhere** for persisted billed amounts:
- `UsageRecord.charged_sparks: int` (replaces `charged_cost: Decimal(12,6)`)
- `BalanceTransaction.amount_sparks: int` (replaces `amount: Decimal(12,4)`)
- `Job.charged_sparks: int` (replaces `charged_cost: Decimal(12,6)`)
- `VisionResult.charged_sparks: int` (replaces `charged_cost: Decimal(12,6)`)

Keep USD only as optional context: `raw_cost_usd`, `markup_multiplier`, etc. — these are for the detail/audit JSON, not for the canonical "how much did we charge" field. Integer sparks avoid float/decimal drift entirely.

### PERFORMANCE

#### P1. `get_usage_summary()` and `get_platform_summary()` load all records into memory (Severity: LOW)
**File:** `billing_service.py:358-384, 628-660`

Both methods call `query.all()` and iterate in Python. For a production system with millions of records, this should be a SQL aggregation.

### SECURITY

#### S1. No rate limit on billing estimate endpoints (Severity: LOW)
All `/billing/*-costs` endpoints are **authenticated** (require Bearer token via `get_current_user`), but have **no rate limiting**. A malicious authenticated user could enumerate pricing by hitting estimate endpoints at high frequency. Low severity since pricing is semi-public anyway, but worth noting.

---

## 3. TARGET ARCHITECTURE — Billing Refactor Blueprint

### 3.1 Core Concept: CostDecision + ActualCost

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  CostDecision    │────▶│  Provider Call    │────▶│  ActualCost      │
│  (persisted      │     │  (execution)     │     │  (persisted      │
│   BEFORE call)   │     │                  │     │   AFTER call)    │
└─────────────────┘     └──────────────────┘     └──────────────────┘
        │                                                  │
        │  idempotency_key prevents                        │
        │  duplicate provider calls                        │
        │                                                  │
        └──────────────── Reconciliation ──────────────────┘
```

**Key invariant:** The CostDecision is the idempotency boundary. If a CostDecision already exists in status `executed`/`charged` for a given `idempotency_key`, the provider call is **skipped entirely**. This prevents both external (provider) and internal (billing) double-charges.

### 3.2 CostDecision Object

```python
class CostDecision:
    """Persisted BEFORE provider execution. Captures the full billing decision
    and serves as the central traceability record for the entire operation."""

    id: int                          # PK
    trace_id: str                    # UUID — THE single GUID that links everything (see 3.2.1)
    user_id: int                     # FK → users
    job_id: int | None               # FK → jobs (if part of a job)
    operation: str                   # enum: tag, describe, embed, generate, edit, train, evaluate, ...
    provider: str                    # openai, anthropic, fal
    model: str                       # exact model ID

    # What matched in the catalog
    catalog_entry_id: int | None     # FK → cost_catalog (exact row that matched)
    catalog_match_tier: str          # "exact", "wildcard", "prefix", "miss"

    # Estimated cost (in sparks, integer)
    estimated_input_tokens: int | None
    estimated_output_tokens: int | None
    estimated_sparks: int            # total estimated charge

    # Pricing snapshot (frozen at decision time)
    cost_per_input_token: Decimal | None
    cost_per_output_token: Decimal | None
    cost_per_call: Decimal | None
    platform_markup: Decimal
    billing_model: str               # "per_token", "per_call", "provider_reported"

    # Full operation context — everything needed to understand what happened
    image_id: int | None             # source image (tag/describe/embed)
    resource_id: int | None          # generated_image_id, lora_model_id, evaluation_id, etc.
    request_snapshot: dict | None    # FULL provider request (see 3.2.2)
    response_snapshot: dict | None   # FULL provider response (see 3.2.2)

    # Idempotency
    idempotency_key: str             # UNIQUE constraint — see key design below

    # Lifecycle
    status: str                      # "pending", "executed", "charged", "failed", "cancelled"
    error_message: str | None        # populated when status=failed
    created_at: datetime
    updated_at: datetime
```

#### 3.2.1 The trace_id — Single GUID for Everything

The `trace_id` is a UUID generated **once** at the start of every billable operation. It propagates to every log line, every DB record, every provider call, and every downstream artifact. Given any anomaly (estimate-vs-actual mismatch, billing failure, user complaint), you start with the `trace_id` and reconstruct the entire operation.

**Where trace_id appears:**

| System | How |
|--------|-----|
| CostDecision | `trace_id` column (indexed) |
| UsageRecord | `trace_id` column (indexed) |
| PipelineLog | `trace_id` column (indexed) |
| BalanceTransaction | `trace_id` column (indexed) |
| Job | Linkable via `CostDecision.job_id` |
| Provider API call | Sent as HTTP header where supported (e.g., `X-Request-ID` for OpenAI, metadata for fal.ai) |
| Application logs | Every `logger.*()` call in a billed operation includes `trace_id` in structured log fields |
| VisionResult | `trace_id` column |
| GeneratedImage | `trace_id` column (nullable, for linking generated output to its billing trace) |

**Generation:**
```python
# At the HTTP endpoint or Celery task entry point — generated ONCE
trace_id = str(uuid.uuid4())

# Propagated via billing context (thread-local)
set_billing_trace(trace_id)

# Every logger call in scope:
logger.info("Starting tag operation", extra={"trace_id": trace_id, "image_id": image_id, ...})

# Passed to Celery task args for fan-out:
process_image_pipeline.delay(image_id=img.id, ..., trace_id=trace_id)
# Children derive sub-traces:
child_trace_id = f"{trace_id}:tag:{image_id}"
```

**For batch/fan-out jobs:** The parent job gets a `trace_id`. Each child operation gets a derived trace: `{parent_trace_id}:{operation}:{resource_id}`. This creates a tree structure: given the parent trace, you can find all children. Given a child trace, you can find the parent.

**Querying child traces:** Finding all children of a parent requires `WHERE trace_id LIKE :parent_trace_id || ':%'`. This works with the btree index on `trace_id` (prefix matching). If query performance becomes a concern at scale, add a `parent_trace_id` column to `cost_decisions` for explicit lookups.

#### 3.2.2 Request & Response Snapshots

The `request_snapshot` and `response_snapshot` fields capture **everything you'd need to reproduce or debug the operation**:

**request_snapshot** (populated BEFORE provider call):
```json
{
  "image_id": 456,
  "image_object_key": "images/abc123.jpg",
  "image_dimensions": {"width": 1024, "height": 768},
  "prompt_text": "Tag this image with flat categorization tags...",
  "prompt_version": "preset:default",
  "temperature": 1.0,
  "max_tokens": 1000,
  "lora_ids": [12],
  "lora_scales": [0.8],
  "resolution": "1024x1024",
  "num_inference_steps": 28,
  "guidance_scale": 3.5,
  "seed": 42,
  "base_model": "flux-dev",
  "edit_model": null,
  "custom_prompt": null
}
```

**response_snapshot** (populated AFTER provider call):
```json
{
  "provider_request_id": "chatcmpl-xyz123",
  "provider_model_used": "gpt-4o-2024-08-06",
  "input_tokens": 1847,
  "output_tokens": 62,
  "total_tokens": 1909,
  "provider_cost_usd": null,
  "duration_ms": 2340,
  "finish_reason": "stop",
  "result_preview": "tags: [portrait, woman, ...]",
  "fal_request_id": null,
  "fal_cost_cents": null
}
```

**What NOT to store:** Raw image bytes (too large). Instead store `image_object_key` — the image is already in storage. For vision calls, the base64 data URI is not stored, just the reference.

**Storage cost:** ~1-2 KB per operation in JSONB. At 10K operations/month = ~20 MB/month. Negligible.

**Idempotency key design:**

Do NOT generate from `(job_id, image_id, operation, attempt)` — a retry might increment `attempt` and defeat idempotency.

Instead, use the **`trace_id`** (the same UUID from section 3.2.1, generated once per user action) as the stable component of the idempotency key:

```python
# trace_id is generated ONCE at the HTTP endpoint or task entry point (see 3.2.1)
# It's already passed to Celery task args:
process_image_pipeline.delay(image_id=img.id, user_id=user.id, job_id=job.id, trace_id=trace_id)

# Idempotency key format:
idempotency_key = f"{user_id}:{trace_id}:{operation}:{resource_id}"

# For fan-out jobs (batch), generate deterministic child keys:
child_key = f"{user_id}:{trace_id}:tag:{image_id}"
```

This ensures:
- Same user action always produces same key (trace_id is stable)
- Celery retries see the same key → find existing decision → skip provider call
- Fan-out children get stable, deterministic keys (trace_id + image_id)

### 3.3 ActualCost Record (extend existing UsageRecord)

```python
class UsageRecord:  # existing, extended
    # ... existing fields ...

    # NEW: Traceability
    trace_id: str | None             # same UUID as CostDecision — links everything
    cost_decision_id: int | None     # FK → cost_decisions

    # NEW: Provider response data (denormalized from CostDecision for query convenience)
    provider_request_id: str | None  # fal request_id, OpenAI request header, etc.

    # NEW: Reconciliation
    delta_sparks: int | None         # actual_sparks - estimated_sparks
    delta_reason: str | None         # "token_count_higher", "fallback_model", "provider_cost_varies"
```

Note: Full request/response snapshots live on CostDecision (the authoritative record). UsageRecord stores only the minimal fields needed for billing queries. The `trace_id` on UsageRecord is denormalized for fast lookups — you can find all billing records for a trace without joining through CostDecision.

### 3.4 BillingOrchestrator (new module)

**File:** `backend/app/services/billing_orchestrator.py`

```python
class BillingOrchestrator:
    """Unified entry point for all billable operations.

    Primary safety: billed tasks have max_retries=0 (no auto-retry).
    Defense-in-depth: idempotency_key prevents duplicate charges on edge cases.
    Traceability: trace_id links every artifact for end-to-end debugging.
    """

    def create_decision(
        self, operation, provider, model,
        trace_id: str,
        idempotency_key: str,
        image_id=None, job_id=None, resource_id=None,
        request_snapshot: dict | None = None,
        estimated_tokens: tuple[int, int] | None = None,
    ) -> tuple[CostDecision, bool]:
        """
        Returns (decision, is_new).

        1. Check for existing decision with same idempotency_key
           - If found with status executed/charged → return (existing, False)
             Caller MUST skip provider call (defense-in-depth).
           - If found with status pending → return (existing, False)
             Another execution is in-flight. Caller exits as duplicate.
        2. Look up catalog entry (snapshot pricing at decision time)
        3. Estimate cost using CostCalculator
        4. Persist CostDecision with full request_snapshot, status="pending"
        5. Return (decision, True) — caller proceeds with provider call
        """

    def record_actual(
        self, decision_id: int,
        actual_input_tokens=None, actual_output_tokens=None,
        provider_cost=None,
        response_snapshot: dict | None = None,
        defer_debit=False,
    ) -> UsageRecord:
        """
        1. Load CostDecision (verify status="pending")
        2. Save response_snapshot on CostDecision
        3. Calculate actual cost (same CostCalculator logic)
        4. Create UsageRecord linked to decision (with trace_id)
        5. Compute delta (estimated vs actual)
        6. Debit balance atomically (unless deferred)
        7. Update decision status → "charged" (or "executed" if deferred)
        """

    def fail_decision(self, decision_id: int, error_message: str):
        """Mark decision as failed. No charge. Store error for debugging."""

    def cancel_decision(self, decision_id: int):
        """Mark decision as cancelled."""
```

**Usage in a task:**
```python
# IMPORTANT: Task decorated with max_retries=0 — no auto-retry for billed operations
@celery_app.task(bind=True, acks_late=False, max_retries=0, reject_on_worker_lost=False)
def tag_image(self, image_id, user_id, job_id, trace_id, ...):
    orchestrator = BillingOrchestrator(db, user_id)

    # Create decision BEFORE provider call — captures full request context
    decision, is_new = orchestrator.create_decision(
        operation="tag", provider="openai", model="gpt-4o",
        trace_id=trace_id,
        idempotency_key=f"{user_id}:{trace_id}:tag:{image_id}",
        image_id=image_id, job_id=job_id,
        request_snapshot={
            "image_id": image_id,
            "image_object_key": image.object_key,
            "image_dimensions": {"width": image.width, "height": image.height},
            "prompt_text": prompt,
            "prompt_version": preset_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
    )

    if not is_new:
        # Defense-in-depth: this is a duplicate (edge case with max_retries=0)
        logger.warning("Duplicate detected", extra={"trace_id": trace_id, "decision_id": decision.id})
        return

    try:
        result = tagger.tag_image(image_data, mime_type, prompt)

        orchestrator.record_actual(
            decision_id=decision.id,
            actual_input_tokens=result.usage.prompt_tokens,
            actual_output_tokens=result.usage.completion_tokens,
            response_snapshot={
                "provider_request_id": result.request_id,
                "provider_model_used": result.model,
                "input_tokens": result.usage.prompt_tokens,
                "output_tokens": result.usage.completion_tokens,
                "finish_reason": result.finish_reason,
                "duration_ms": duration_ms,
                "result_preview": str(result.tags)[:200],
            },
            defer_debit=is_billing_deferred(),
        )
    except Exception as e:
        orchestrator.fail_decision(decision.id, error_message=str(e))
        raise  # Task fails, user sees FAILED status, can retry manually
```

### 3.5 Shared CostCalculator (extract from BillingService)

**File:** `backend/app/services/cost_calculator.py`

```python
class CostBreakdown:
    """Immutable result of cost calculation."""
    raw_cost_usd: Decimal           # provider cost before markup
    markup: Decimal                  # multiplier applied
    charged_sparks: int             # final charge in sparks (integer)
    billing_model: str              # per_token, per_call, provider_reported
    detail: dict                    # full breakdown for audit

class CostCalculator:
    """Pure calculation logic, shared by estimate AND actual paths.

    This is the ONLY place cost math happens. Both estimate endpoints
    and actual billing call the same functions.
    """

    @staticmethod
    def calculate_from_tokens(
        input_tokens: int, output_tokens: int,
        cost_per_input_token: Decimal, cost_per_output_token: Decimal,
        cost_per_call: Decimal, platform_markup: Decimal,
    ) -> CostBreakdown:
        """Token-based cost calculation."""

    @staticmethod
    def calculate_from_provider_cost(
        provider_cost: Decimal, platform_markup: Decimal,
    ) -> CostBreakdown:
        """Provider-reported cost calculation."""

    @staticmethod
    def estimate_tokens(
        provider: str, model: str, operation: str,
        image_width: int | None = None, image_height: int | None = None,
        prompt_text: str | None = None, tags: list | None = None, description: str | None = None,
    ) -> tuple[int, int]:
        """Unified token estimation (wraps token_estimator.py)."""
```

### 3.6 File Layout

```
backend/app/services/
  billing_orchestrator.py   # NEW: CostDecision lifecycle + idempotency
  cost_calculator.py        # NEW: Shared calc (extract from billing_service)
  billing_service.py        # KEEP: Balance mgmt, reporting, catalog CRUD (debit_usage_atomic)
  billing_context.py        # KEEP: Thread-local context
  token_estimator.py        # KEEP: Token estimation formulas (called by CostCalculator)
```

### 3.7 Integration Pattern — Inversion of Billing Trigger

**Before (current) — billing as side-effect of logging:**
```python
# In provider class
result = openai_client.chat.completions.create(...)
write_log(category=API_CALL, input_tokens=result.usage.prompt_tokens, ...)
# Billing happens as a side-effect inside write_log → record_usage_standalone()
# The task/route code has NO control over billing
```

**After (proposed) — billing as explicit orchestrated step:**
```python
# In task/route code, BEFORE provider call:
decision, is_new = orchestrator.create_decision(...)
if not is_new:
    return  # skip duplicate

# Provider call (unchanged internally, but logging becomes PASSIVE):
result = tagger.tag_image(image_data, mime_type, prompt)
# write_log() still fires for operational logging, but does NOT trigger billing

# AFTER provider call, explicit billing:
orchestrator.record_actual(decision_id=decision.id, ...)
```

**Critical architectural point:** With this pattern, `write_log()` no longer triggers `record_usage_standalone()`. Logging becomes purely observational. Billing is an explicit step owned by the task/route code via the orchestrator. This is the fundamental inversion that makes the system controllable.

**Migration strategy:** Don't try to invert everything at once. Start with the highest-volume flows (pipeline + generate/edit). Leave legacy paths behind a feature flag:
```python
# billing_context.py
ORCHESTRATOR_ENABLED_OPS = {"tag", "describe", "embed", "generate", "edit"}

# log_service.py
if operation not in ORCHESTRATOR_ENABLED_OPS:
    # Legacy path: billing as side-effect (unchanged)
    record_usage_standalone(...)
# else: orchestrator handles billing; logging is passive
```

**End state:** Once all operations are migrated to the orchestrator, `record_usage_standalone()` in `log_service.py` and its billing trigger inside `write_log()` become dead code. Remove both and the `ORCHESTRATOR_ENABLED_OPS` feature flag. `write_log()` remains as a pure operational logging function.

### 3.8 Migration Plan (Incremental, Non-Breaking)

See Phase plan in Section 6.

---

## 4. INSTRUMENTATION & MONITORING PLAN

This section covers not just billing debugging, but **system-wide operation traceability**. The core idea: every operation that touches a provider API gets a `trace_id` (UUID) that links every artifact — from the user clicking "Describe" to the final charged sparks, including the raw request, the raw response, the image, the prompt, the model, and every intermediate step.

### 4.1 Structured Logging — trace_id in Every Log Line

Every log statement within a billed operation must include the `trace_id`. This enables grep/search across all logs for a single operation.

**Implementation:** Add a logging filter that reads `trace_id` from billing context (thread-local):

```python
# backend/app/core/logging.py
class TraceIdFilter(logging.Filter):
    def filter(self, record):
        from app.services.billing_context import get_billing_trace
        record.trace_id = get_billing_trace() or "-"
        return True

# Log format includes trace_id:
LOG_FORMAT = '%(asctime)s %(levelname)s [%(trace_id)s] %(name)s: %(message)s'
```

This means **every** log line emitted during a billed operation — not just billing-specific ones, but provider calls, storage writes, image processing, etc. — carries the trace_id. No code changes needed per-log-site; the filter injects it automatically.

**Structured billing events** (emitted by the orchestrator at key lifecycle points):

```json
{"event": "op.decision_created", "trace_id": "a1b2c3d4-...", "user_id": 1, "job_id": 15,
 "operation": "tag", "provider": "openai", "model": "gpt-4o", "image_id": 456,
 "catalog_entry_id": 7, "catalog_match_tier": "exact", "estimated_sparks": 7}
```
```json
{"event": "op.provider_call_start", "trace_id": "a1b2c3d4-...", "provider": "openai",
 "model": "gpt-4o", "image_id": 456}
```
```json
{"event": "op.provider_call_complete", "trace_id": "a1b2c3d4-...", "duration_ms": 2340,
 "input_tokens": 1847, "output_tokens": 62, "provider_request_id": "chatcmpl-xyz"}
```
```json
{"event": "op.actual_recorded", "trace_id": "a1b2c3d4-...", "usage_record_id": 123,
 "actual_sparks": 8, "delta_sparks": 1, "delta_reason": "token_count_higher"}
```
```json
{"event": "op.failed", "trace_id": "a1b2c3d4-...", "error": "OpenAI rate limit exceeded",
 "decision_status": "failed"}
```

### 4.2 New DB Schema

**New table: `cost_decisions`** — the central traceability record

```sql
CREATE TABLE cost_decisions (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(256) NOT NULL,  -- UUID, the single GUID for everything
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id INTEGER REFERENCES jobs(id),
    operation VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    model VARCHAR(128) NOT NULL,

    -- Catalog match
    catalog_entry_id INTEGER REFERENCES cost_catalog(id),
    catalog_match_tier VARCHAR(16),  -- exact, wildcard, prefix, miss

    -- Estimated cost
    estimated_input_tokens INTEGER,
    estimated_output_tokens INTEGER,
    estimated_sparks INTEGER,

    -- Pricing snapshot (frozen at decision time)
    cost_per_input_token NUMERIC(20,12),
    cost_per_output_token NUMERIC(20,12),
    cost_per_call NUMERIC(12,6),
    platform_markup NUMERIC(5,4),
    billing_model VARCHAR(32),       -- per_token, per_call, provider_reported

    -- Full operation context
    image_id INTEGER,
    resource_id INTEGER,             -- generated_image_id, lora_model_id, etc.
    request_snapshot JSONB,          -- full provider request params (see 3.2.2)
    response_snapshot JSONB,         -- full provider response data (see 3.2.2)

    -- Lifecycle
    status VARCHAR(16) NOT NULL DEFAULT 'pending',
    error_message TEXT,              -- populated when status=failed
    idempotency_key VARCHAR(256) NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX uq_cost_decisions_idempotency ON cost_decisions(idempotency_key);
CREATE INDEX ix_cost_decisions_trace ON cost_decisions(trace_id);
CREATE INDEX ix_cost_decisions_user_created ON cost_decisions(user_id, created_at DESC);
CREATE INDEX ix_cost_decisions_job ON cost_decisions(job_id) WHERE job_id IS NOT NULL;
CREATE INDEX ix_cost_decisions_status ON cost_decisions(status) WHERE status = 'pending';
CREATE INDEX ix_cost_decisions_image ON cost_decisions(image_id) WHERE image_id IS NOT NULL;
```

**Extend `usage_records`:**
```sql
ALTER TABLE usage_records ADD COLUMN trace_id VARCHAR(256);
ALTER TABLE usage_records ADD COLUMN cost_decision_id INTEGER REFERENCES cost_decisions(id);
ALTER TABLE usage_records ADD COLUMN provider_request_id VARCHAR(256);
ALTER TABLE usage_records ADD COLUMN delta_sparks INTEGER;
ALTER TABLE usage_records ADD COLUMN delta_reason VARCHAR(128);

CREATE INDEX ix_usage_records_trace ON usage_records(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX ix_usage_records_decision ON usage_records(cost_decision_id) WHERE cost_decision_id IS NOT NULL;
```

**Extend `pipeline_logs`:**
```sql
ALTER TABLE pipeline_logs ADD COLUMN trace_id VARCHAR(256);
ALTER TABLE pipeline_logs ADD COLUMN billing_failed BOOLEAN DEFAULT FALSE;

CREATE INDEX ix_pipeline_logs_trace ON pipeline_logs(trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX ix_pipeline_logs_billing_failed ON pipeline_logs(billing_failed) WHERE billing_failed = TRUE;
```

**Extend `balance_transactions`:**
```sql
ALTER TABLE balance_transactions ADD COLUMN trace_id VARCHAR(256);

CREATE INDEX ix_balance_transactions_trace ON balance_transactions(trace_id) WHERE trace_id IS NOT NULL;
```

**Required: `billing_anomalies` table** (used by BILLING_STRICT_MODE non-strict path in C5, and for billing failure tracking in C6 — include in the Phase 0 migration alongside trace_id columns):
```sql
CREATE TABLE billing_anomalies (
    id SERIAL PRIMARY KEY,
    trace_id VARCHAR(256),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    anomaly_type VARCHAR(32) NOT NULL,  -- CATALOG_MISS, BILLING_FAILED, DUPLICATE_DETECTED, etc.
    provider VARCHAR(32),
    model VARCHAR(128),
    operation VARCHAR(64),
    detail JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_billing_anomalies_type ON billing_anomalies(anomaly_type, created_at DESC);
CREATE INDEX ix_billing_anomalies_trace ON billing_anomalies(trace_id) WHERE trace_id IS NOT NULL;
```

### 4.3 Trace Lookup Query

The fundamental debugging query — given a `trace_id`, show everything:

```sql
-- Full operation trace for trace_id = 'a1b2c3d4-...'
SELECT
    'decision' as record_type,
    cd.id, cd.trace_id, cd.operation, cd.provider, cd.model,
    cd.status, cd.estimated_sparks,
    cd.catalog_match_tier, cd.catalog_entry_id,
    cd.image_id, cd.resource_id,
    cd.request_snapshot, cd.response_snapshot,
    cd.error_message,
    cd.created_at, cd.updated_at
FROM cost_decisions cd WHERE cd.trace_id = :trace_id

UNION ALL

SELECT
    'usage' as record_type,
    ur.id, ur.trace_id, ur.operation, ur.provider, ur.model,
    NULL, NULL,
    NULL, NULL,
    NULL, NULL,
    ur.detail::jsonb, NULL,
    NULL,
    ur.created_at, NULL
FROM usage_records ur WHERE ur.trace_id = :trace_id

UNION ALL

SELECT
    'transaction' as record_type,
    bt.id, bt.trace_id, bt.transaction_type, NULL, NULL,
    NULL, bt.amount,
    NULL, NULL,
    NULL, NULL,
    NULL, NULL,
    bt.description,
    bt.created_at, NULL
FROM balance_transactions bt WHERE bt.trace_id = :trace_id

UNION ALL

SELECT
    'log' as record_type,
    pl.id, pl.trace_id, pl.operation, pl.provider, pl.model,
    pl.level::text, NULL,
    pl.task_name, NULL,
    pl.image_id, NULL,
    pl.extra::jsonb, NULL,
    pl.message,
    pl.created_at, NULL
FROM pipeline_logs pl WHERE pl.trace_id = :trace_id

ORDER BY created_at;
```

This single query returns the complete timeline of a single operation — from decision creation through provider call to billing and debit.

### 4.4 Billing Timeline Query (by Job)

For batch operations, query by `job_id` to see all operations in a job:

```sql
SELECT
    cd.id as decision_id,
    cd.trace_id,
    cd.operation,
    cd.provider || '/' || cd.model as provider_model,
    cd.catalog_match_tier,
    cd.estimated_sparks,
    cd.status as decision_status,
    cd.image_id,
    cd.created_at as decision_at,
    ur.id as usage_record_id,
    ur.delta_sparks,
    ur.delta_reason,
    ur.provider_request_id,
    ur.created_at as charged_at,
    bt.id as txn_id,
    bt.amount as debit_sparks,
    bt.created_at as debited_at
FROM cost_decisions cd
LEFT JOIN usage_records ur ON ur.cost_decision_id = cd.id
LEFT JOIN balance_transactions bt ON bt.reference_id = ur.id AND bt.transaction_type = 'debit'
WHERE cd.job_id = :job_id
ORDER BY cd.created_at;
```

**Note on the join:** `balance_transactions.reference_id` stores `usage_record_id` for inline debits (set in `debit_usage()` at `billing_service.py:132`). For deferred billing (`finalize_job_billing()`), the combined debit has `reference_id=NULL`. The LEFT JOIN handles both cases — inline debits match; deferred debits show as NULL here and can be found via `balance_transactions.trace_id` or description matching.

### 4.5 Admin API Endpoints

**`GET /admin/trace/{trace_id}`** — Full operation trace

Returns everything linked to a trace_id in chronological order: decision, provider request/response, usage, transaction, logs.

```json
{
  "trace_id": "a1b2c3d4-...",
  "operation": "tag",
  "user": {"id": 1, "email": "stuart.leal23@gmail.com"},
  "job_id": 15,
  "decision": {
    "id": 42,
    "status": "charged",
    "estimated_sparks": 7,
    "catalog_match": {"tier": "exact", "entry_id": 7},
    "pricing_snapshot": {
      "cost_per_input_token": 0.0000025,
      "cost_per_output_token": 0.00001,
      "platform_markup": 2.0,
      "billing_model": "per_token"
    },
    "request": {
      "image_id": 456,
      "image_object_key": "images/abc123.jpg",
      "image_dimensions": {"width": 1024, "height": 768},
      "prompt_text": "Tag this image with flat categorization tags...",
      "temperature": 1.0,
      "max_tokens": 1000
    },
    "response": {
      "provider_request_id": "chatcmpl-xyz",
      "provider_model_used": "gpt-4o-2024-08-06",
      "input_tokens": 1847,
      "output_tokens": 62,
      "duration_ms": 2340,
      "finish_reason": "stop",
      "result_preview": "tags: [portrait, woman, studio, ...]"
    }
  },
  "billing": {
    "usage_record_id": 123,
    "actual_sparks": 8,
    "delta_sparks": 1,
    "delta_reason": "token_count_higher",
    "transaction_id": 456,
    "debit_sparks": -8
  },
  "logs": [
    {"timestamp": "...", "level": "INFO", "message": "Starting tag operation"},
    {"timestamp": "...", "level": "INFO", "message": "BILLING | user=... sparks=8.0"},
    {"timestamp": "...", "level": "INFO", "message": "Tag complete: 12 tags"}
  ]
}
```

**`GET /admin/traces`** — Paginated trace search

Filters: `user_id`, `job_id`, `operation`, `provider`, `model`, `status`, `image_id`, `date_range`, `has_delta` (boolean: only show traces with estimate-vs-actual mismatch), `has_error` (boolean: only show failed).

**`GET /billing/admin/timeline/{job_id}`** — Job billing timeline (aggregation of all traces in a job)

**`GET /billing/admin/reconciliation`** — Delta analysis: traces where |delta_sparks| > threshold, grouped by operation/provider

**`GET /billing/admin/anomalies`** — Catalog misses, billing failures, duplicates detected

### 4.6 Operations Monitor — Scalable, Cheap Frontend

The monitoring UI is a single admin page (`/admin/monitor`) that serves as **the front-end to the system database and logs**. It's not a separate service — it queries the existing tables via the admin API endpoints above.

**Design: Single-page with search + detail**

```
┌─────────────────────────────────────────────────────────────────┐
│  Operations Monitor                                       [Admin] │
├─────────────────────────────────────────────────────────────────┤
│  Search: [trace_id / job_id / image_id / user_id]               │
│                                                                   │
│  Filters: [Operation ▼] [Provider ▼] [Status ▼] [Date range]    │
│           [□ Has delta] [□ Has error] [□ Anomalies only]         │
├─────────────────────────────────────────────────────────────────┤
│  Results (245 traces)                                             │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ trace_id    │ op    │ provider │ status  │ est │ actual │ Δ │ │
│  │ a1b2...     │ tag   │ openai   │ charged │ 7   │ 8      │+1 │ │
│  │ c3d4...     │ gen   │ fal      │ charged │ 70  │ 70     │ 0 │ │
│  │ e5f6...     │ desc  │ openai   │ failed  │ 5   │ —      │ — │ │
│  └─────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│  Detail: trace a1b2c3d4...                                       │
│  ┌─ Decision ──────────────────────────────────────────────────┐ │
│  │ Operation: tag | Provider: openai/gpt-4o                     │ │
│  │ Image: #456 (images/abc123.jpg) [🔗 View]                   │ │
│  │ Catalog: exact match → entry #7                              │ │
│  │ Estimated: 7 sparks (1847 in + 62 out tokens)                │ │
│  │ Actual: 8 sparks (+1 delta: token_count_higher)              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌─ Request ───────────────────────────────────────────────────┐ │
│  │ Prompt: "Tag this image with flat categorization..."         │ │
│  │ Temperature: 1.0 | Max tokens: 1000                          │ │
│  │ Image: 1024x768 | Prompt version: preset:default             │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌─ Response ──────────────────────────────────────────────────┐ │
│  │ Provider request: chatcmpl-xyz | Model: gpt-4o-2024-08-06   │ │
│  │ Tokens: 1847 in + 62 out | Duration: 2340ms                  │ │
│  │ Result: tags: [portrait, woman, studio, ...]                  │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌─ Billing ───────────────────────────────────────────────────┐ │
│  │ UsageRecord #123 | Transaction #456 | Debit: -8 sparks       │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ┌─ Logs (3 entries) ──────────────────────────────────────────┐ │
│  │ 10:00:00 INFO Starting tag operation                          │ │
│  │ 10:00:02 INFO BILLING | sparks=8.0                            │ │
│  │ 10:00:02 INFO Tag complete: 12 tags                           │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

**Why this is cheap:**
- No new infrastructure — queries existing Postgres tables via FastAPI admin endpoints
- Frontend is one React page with TanStack Query + a detail drawer (same pattern as existing ImageDrawer)
- Search by trace_id is O(1) with index — queries are fast even at scale
- No external log aggregation service needed — structured logs go to stdout, but the *source of truth* for operations is the `cost_decisions` table with its JSONB snapshots
- Storage: ~2 KB per operation in JSONB. At 100K ops/month = ~200 MB/month in Postgres. Years of data fits in a single table.

**Why this is scalable:**
- The `cost_decisions` table is append-mostly (only `status` and `response_snapshot` get updated). Reads are indexed by trace_id, user_id, job_id, image_id.
- For high-volume: partition `cost_decisions` by `created_at` (monthly). Old partitions can be detached and archived.
- For cross-service tracing (if you ever add microservices): the `trace_id` is a standard UUID that can propagate via HTTP headers. OpenTelemetry-compatible from day one.

**Quick wins that don't require the full Operations Monitor:**
1. **`/admin/trace/{trace_id}` endpoint** — usable from browser or curl immediately
2. **Link from Job detail page** — each job step shows its trace_id as a clickable link to the trace detail
3. **Link from Billing logs page** — each UsageRecord row shows its trace_id
4. **grep in logs** — `grep "a1b2c3d4" backend.log` finds every log line for an operation

### 4.7 Dashboard Metrics (Bonus — Zero-Cost with Existing DB)

Add a `/admin/metrics` endpoint that returns aggregate health indicators. Poll from the existing admin page. No Prometheus/Grafana needed.

```json
{
  "last_hour": {
    "total_operations": 142,
    "failed_operations": 3,
    "catalog_misses": 0,
    "billing_failures": 0,
    "avg_delta_sparks": 0.3,
    "max_delta_sparks": 4,
    "total_sparks_charged": 1847,
    "total_raw_cost_usd": 0.92
  },
  "alerts": [
    {"type": "HIGH_DELTA", "count": 2, "message": "2 operations with delta > 10 sparks in last hour"},
    {"type": "CATALOG_MISS", "count": 0},
    {"type": "BILLING_FAILED", "count": 0}
  ]
}
```

Implemented as simple SQL aggregates over `cost_decisions` WHERE `created_at > NOW() - INTERVAL '1 hour'`. Cheap, no external dependencies, surfaces problems immediately.

---

## 5. TEST PLAN

### 5.1 Unit Tests — CostCatalog Matching

```python
# backend/tests/unit/test_catalog_matching.py

class TestCatalogMatching:
    """Test _get_catalog_entry() 3-tier fallback."""

    def test_exact_match(self, db_session, seed_catalog):
        """Exact provider/model/operation returns correct entry."""

    def test_wildcard_model_fallback(self, db_session):
        """Unknown model falls back to provider/*/operation."""

    def test_prefix_wildcard_match(self, db_session):
        """'openrouter/*' matches 'openrouter/qwen-vl-max'."""

    def test_prefix_wildcard_no_match(self, db_session):
        """'openrouter/*' does NOT match 'openai/gpt-4o'."""

    def test_no_match_returns_none(self, db_session):
        """Completely unknown provider/model/operation → None."""

    def test_no_match_strict_mode_raises(self, db_session, monkeypatch):
        """With BILLING_STRICT_MODE=true, catalog miss raises BillingCatalogMissError."""

    def test_no_match_non_strict_records_anomaly(self, db_session, monkeypatch):
        """With BILLING_STRICT_MODE=false, catalog miss records BillingAnomaly."""

    def test_inactive_entries_excluded(self, db_session):
        """Deactivated catalog entries are never returned."""

    def test_multiple_prefix_wildcards_longest_wins(self, db_session):
        """When 'openrouter/*' and 'openrouter/qwen*' both match,
        longest prefix 'openrouter/qwen*' is selected."""

    def test_exact_takes_priority_over_wildcard(self, db_session):
        """Even if wildcard exists, exact match is preferred."""
```

### 5.2 Table-Driven Cost Calculation Tests

```python
# backend/tests/unit/test_cost_calculator.py

@pytest.mark.parametrize("input_tokens,output_tokens,per_in,per_out,per_call,markup,expected_sparks", [
    (1000, 100, "0.0000025", "0.00001", "0", "2.0", 7),        # OpenAI gpt-4o tag
    (500, 300, "0.00000015", "0.0000006", "0", "2.0", 1),       # gpt-4o-mini describe (0.51 → 1 spark)
    (0, 0, "0", "0", "0.035", "2.0", 70),                       # fal flux-lora generate
    (0, 0, "0", "0", "2.0", "2.0", 4000),                       # fal training
    (2000, 50, "0.0000002", "0.0000005", "0", "2.0", 1),        # grok-4-fast tag (0.85 → 1 spark)
])
def test_catalog_based_cost(input_tokens, output_tokens, per_in, per_out, per_call, markup, expected_sparks):
    """Verify cost calculation for known scenarios. All expected values in integer sparks."""

@pytest.mark.parametrize("provider_cost,markup,expected_sparks", [
    ("0.035", "2.0", 70),       # fal.ai generate
    ("0.075", "2.0", 150),      # qwen-max-edit
    ("0.00342", "2.0", 7),      # fal.ai arbitrary cost (6.84 → 7 sparks)
])
def test_provider_reported_cost(provider_cost, markup, expected_sparks):
    """Verify provider-reported cost path. Integer sparks."""
```

### 5.3 Integration Tests — No-Retry Policy & Defense-in-Depth

```python
# backend/tests/integration/test_billing_safety.py

class TestNoRetryPolicy:
    """Verify all billed tasks have max_retries=0."""

    @pytest.mark.parametrize("task_name", [
        "app.workers.tasks.tag_image",
        "app.workers.tasks.describe_image",
        "app.workers.tasks.embed_image",
        "app.workers.tasks.summarize_cluster",
        "app.workers.tasks.process_image_pipeline",
        "app.workers.generation_tasks.generate_image",
        "app.workers.generation_tasks.edit_image",
        "app.workers.generation_tasks.train_lora",
        "app.workers.generation_tasks.evaluate_lora",
    ])
    def test_billed_task_has_no_retries(self, task_name):
        """Every task that calls a paid provider API must have max_retries=0."""
        from app.workers.celery_app import celery_app
        task = celery_app.tasks[task_name]
        assert task.max_retries == 0, f"{task_name} allows retries — billed tasks must not retry"
        assert task.acks_late is False, f"{task_name} has acks_late=True — risks redelivery on crash"


class TestIdempotencyDefenseInDepth:
    """Defense-in-depth: idempotency_key prevents duplicate charges on edge cases
    (Celery visibility timeout, broker redelivery) even with max_retries=0."""

    def test_create_decision_idempotent(self):
        """Same idempotency_key returns existing decision with is_new=False."""
        decision1, is_new1 = orchestrator.create_decision(idempotency_key="key1", ...)
        assert is_new1 is True
        decision2, is_new2 = orchestrator.create_decision(idempotency_key="key1", ...)
        assert is_new2 is False
        assert decision2.id == decision1.id

    def test_duplicate_skips_provider_call(self):
        """When decision exists with status=charged, caller skips provider call."""
        decision, _ = orchestrator.create_decision(idempotency_key="key1", ...)
        orchestrator.record_actual(decision.id, ...)
        _, is_new = orchestrator.create_decision(idempotency_key="key1", ...)
        assert is_new is False  # caller MUST skip provider call

    def test_fan_out_child_keys_stable(self):
        """Batch child keys are deterministic: same trace_id + image_id → same key."""
        key1 = f"1:trace_abc:tag:42"
        key2 = f"1:trace_abc:tag:42"
        assert key1 == key2


class TestAtomicDebit:
    """Verify atomic debit guard prevents negative balances."""

    def test_atomic_debit_prevents_negative_balance(self):
        """Concurrent debits cannot drive balance below zero."""
        # Set balance to 10 sparks
        # Fire 5 concurrent debit_usage_atomic(amount=5) calls
        # Exactly 2 should succeed, 3 should return None
        # Final balance should be 0, not negative

    def test_deferred_finalize_idempotent(self):
        """Calling finalize_job_billing twice doesn't double-debit."""
```

### 5.4 Contract Tests — Provider Adapters

```python
# backend/tests/contract/test_provider_billing_contract.py

class TestProviderBillingContract:
    """Each provider must return usage data in expected format."""

    def test_openai_returns_token_counts(self, mock_openai):
        """OpenAI response.usage has prompt_tokens and completion_tokens."""

    def test_anthropic_returns_token_counts(self, mock_anthropic):
        """Anthropic response.usage has input_tokens and output_tokens."""

    def test_fal_returns_provider_cost(self, mock_fal):
        """fal.ai result has 'cost' field in USD."""

    def test_fal_vision_returns_tokens_and_cost(self, mock_fal_vision):
        """fal.ai OpenRouter returns both usage.{tokens} and usage.cost."""

    def test_all_providers_return_request_id(self, mock_all_providers):
        """Every provider response includes a request_id for audit trail."""
```

### 5.5 Minimal Test Harness

```python
# backend/tests/conftest.py additions

@pytest.fixture
def seed_catalog(db_session):
    """Seed cost_catalog with representative entries for testing."""
    entries = [
        CostCatalog(provider="openai", model="gpt-4o", operation="tag",
                     cost_per_input_token=Decimal("0.0000025"),
                     cost_per_output_token=Decimal("0.00001"),
                     platform_markup=Decimal("2.0")),
        CostCatalog(provider="fal", model="*", operation="generate",
                     cost_per_call=Decimal("0.035"),
                     platform_markup=Decimal("2.0")),
        CostCatalog(provider="openrouter", model="openrouter/*", operation="tag",
                     cost_per_input_token=Decimal("0.0000002"),
                     cost_per_output_token=Decimal("0.0000005"),
                     platform_markup=Decimal("2.0")),
        # Longer prefix wildcard for deterministic matching test
        CostCatalog(provider="openrouter", model="openrouter/qwen*", operation="tag",
                     cost_per_input_token=Decimal("0.0000003"),
                     cost_per_output_token=Decimal("0.0000008"),
                     platform_markup=Decimal("2.0")),
    ]
    db_session.add_all(entries)
    db_session.commit()
    return entries

@pytest.fixture
def billing_service(db_session, test_user):
    """BillingService for test_user with seeded balance."""
    svc = BillingService(db_session, test_user.id)
    svc.add_credits(Decimal("10000"), "Test credits")
    return svc

@pytest.fixture
def orchestrator(db_session, test_user, seed_catalog):
    """BillingOrchestrator for test_user with seeded catalog and balance."""
    return BillingOrchestrator(db_session, test_user.id)
```

---

## 6. PHASED IMPLEMENTATION PLAN

### Phase 0: Safety + Observability (Low Risk)
**Goal:** Fix the worst correctness bugs, disable dangerous retries, and make the current system debuggable — without changing billing architecture.

| # | Action | Effort | Risk | Description |
|---|--------|--------|------|-------------|
| 0.1 | **Disable retries on all billed tasks** | S | Low | Add `acks_late=False, max_retries=0, reject_on_worker_lost=False` to every task that calls a paid provider API. Match the existing `train_lora` pattern. On failure: set Job.status=FAILED, user retries via UI. |
| 0.2 | **Atomic debit guard** | S | Low | Replace `debit_usage()` with `debit_usage_atomic()`: `UPDATE ... WHERE balance >= :amt`. Eliminates TOCTOU gap. No schema change needed. |
| 0.3 | **Fix `_get_latest_charged_cost()` race** | S | Low | Return UsageRecord ID from `record_usage_standalone()` via billing context thread-local. In `vision.py`, read the ID from context instead of querying by timestamp. |
| 0.4 | **Catalog miss: strict mode + `billing_anomalies` table** | S | Low | Create `billing_anomalies` table (Alembic migration). Add `BILLING_STRICT_MODE` env var (default true). On miss: strict = raise `BillingCatalogMissError`; non-strict = record anomaly + proceed with $0. Store (provider, model, operation) in anomaly. |
| 0.5 | **Move `finalize_job_billing()` to finally blocks** | S | Low | `batch_generate`, `batch_edit` — wrap finalization in try/finally so `Job.charged_cost` is always set. |
| 0.6 | **Stop swallowing billing failures** | S | Low | In `write_log()` line 86-87: instead of `logger.warning`, add `billing_failed=True` flag to PipelineLog (new column) and emit error metric. |
| 0.7 | **Add `catalog_entry_id` + `catalog_match_tier` to UsageRecord.detail** | S | Low | In `_calculate_cost()`, include the matched CostCatalog.id and match tier in the detail JSON. |
| 0.8 | **Add `trace_id` column to PipelineLog + UsageRecord + BalanceTransaction** | S | Low | Alembic migration. Nullable VARCHAR(256) + index. Begin populating from billing context. Foundation for all tracing. |
| 0.9 | **Add structured logging with trace_id** | M | Low | TraceIdFilter on logger. Emit JSON billing events. Every log line in a billed operation carries trace_id automatically. |

### Phase 1: CostDecision + Orchestrator + Operations Monitor (Medium Risk)
**Goal:** Persist decisions with full request/response context. Unify estimate and actual. Build the monitoring UI.

| # | Action | Effort | Risk | Description |
|---|--------|--------|------|-------------|
| 1.1 | **Extract `CostCalculator` from `BillingService`** | M | Low | Pure functions, no behavior change. Both estimate endpoints and `_calculate_cost()` call the same functions. |
| 1.2 | **Create `cost_decisions` table + model** | M | Low | Alembic migration with trace_id, idempotency_key UNIQUE, request/response JSONB snapshots. |
| 1.3 | **Create `BillingOrchestrator`** | M | Med | create_decision (with request_snapshot) + record_actual (with response_snapshot) + fail/cancel. |
| 1.4 | **Wire `process_image_pipeline` to orchestrator** | M | Med | First task. Generate trace_id, pass to task args. Capture full request/response. Feature flag per-operation. write_log() becomes passive for migrated ops. |
| 1.5 | **Wire `generate_image` + `edit_image` to orchestrator** | M | Med | Validates inline billing + fal.ai provider cost capture. |
| 1.6 | **Wire vision API endpoint to orchestrator** | M | Med | `POST /vision/analyze` is an inline HTTP route (not a Celery task), so orchestrator.create_decision() is called directly in the route handler. Eliminates the C1 race in `_get_latest_charged_cost()` — cost comes from the CostDecision, not a timestamp query. |
| 1.7 | **`GET /admin/trace/{trace_id}` endpoint** | M | Low | The single most useful debugging tool. Returns full operation story from cost_decisions + usage_records + pipeline_logs + balance_transactions. |
| 1.8 | **Operations Monitor page (frontend)** | L | Low | Search by trace_id/job_id/user_id/image_id. Results table + detail drawer. Same React patterns as existing admin pages. |
| 1.9 | **Wire remaining tasks incrementally** | L | Med | One task at a time, each behind feature flag, each independently testable. |

### Phase 2: Invariants + Unit Standardization (Medium Risk)
**Goal:** Stronger DB constraints, unit standardization, defense-in-depth idempotency.

| # | Action | Effort | Risk | Description |
|---|--------|--------|------|-------------|
| 2.1 | **Defense-in-depth: idempotency_key check before provider call** | M | Med | Even with max_retries=0, edge cases exist (Celery visibility timeout, broker redelivery). CostDecision idempotency_key provides a second layer: if key exists with status executed/charged → skip provider call. |
| 2.2 | **Add debit uniqueness constraint** | S | Med | Add unique index on `balance_transactions(reference_type, reference_id)` or equivalent to prevent duplicate debits for same UsageRecord. |
| 2.3 | **Standardize to integer sparks** | L | Med | Migration: add `*_sparks: int` columns alongside existing `*_cost: Decimal`. Dual-write during transition. Then migrate readers. Then drop old columns. |
| 2.4 | **Catalog matching: longest prefix wins** | S | Low | In Tier 3 of `_get_catalog_entry()`, sort wildcards by prefix length descending. Take first match. Or add `priority` column to CostCatalog. |
| 2.5 | **Migrate estimate endpoints to use CostCalculator** | M | Med | `/billing/*-costs` use same calc functions as actuals. Estimate-vs-actual deltas become meaningful. |
| 2.6 | **Balance reservation (optional, long-term)** | L | High | Reserve estimated sparks at decision time (`status=reserved`), settle to actual after execution. |

### Phase 3: Reconciliation + Dashboards (Low Risk)
**Goal:** Automated anomaly detection, reconciliation reporting, health dashboards.

| # | Action | Effort | Risk | Description |
|---|--------|--------|------|-------------|
| 3.1 | **Reconciliation API endpoint** | M | Low | `GET /billing/admin/reconciliation` — delta analysis grouped by operation/provider. Surfaces systematic estimate inaccuracy. |
| 3.2 | **Anomalies API endpoint** | S | Low | `GET /billing/admin/anomalies` — catalog misses, billing failures, with "auto-create catalog entry" action. |
| 3.3 | **`/admin/metrics` health dashboard** | M | Low | Aggregate SQL queries over cost_decisions: ops/hour, failure rate, avg delta, alerts for high delta / catalog miss / billing failure. |
| 3.4 | **Reconciliation + Anomalies tabs in Operations Monitor** | M | Low | Extend the Phase 1 frontend page with delta threshold filters and anomaly grouping. |
| 3.5 | **Evaluation cost estimate endpoint** | S | Low | `GET /billing/evaluation-costs` — currently missing, users can't see cost before evaluating. |
| 3.6 | **Cluster summarize cost estimate** | S | Low | Currently no estimate shown to user before summarizing clusters. |

---

## TOP 10 ACTIONS (Priority Order)

| # | Action | Phase | Effort | Risk | Why This Order |
|---|--------|-------|--------|------|----------------|
| 1 | **Disable retries on all billed tasks** (`max_retries=0`) | 0 | S | Low | Eliminates the entire class of double-charge AND double-provider-cost bugs. One decorator change per task. Matches existing `train_lora` pattern. |
| 2 | **Atomic debit guard** (`UPDATE WHERE balance >= :amt`) | 0 | S | Low | Prevents negative balances. Simplest high-value correctness fix. Zero schema change. |
| 3 | **Fix `_get_latest_charged_cost()` race** in vision.py | 0 | S | Low | Active correctness bug: wrong cost attributed under concurrency. |
| 4 | **Catalog miss: strict mode** | 0 | S | Low | Revenue leakage + config drift. Fail-closed by default in prod. |
| 5 | **Add `trace_id` to PipelineLog + UsageRecord + BalanceTransaction** | 0 | S | Low | Foundation for all tracing. One migration, start populating immediately. Enables grep-based debugging today. |
| 6 | **Create `cost_decisions` table with request/response snapshots** | 1 | M | Low | The central traceability record. Every operation fully captured and queryable. |
| 7 | **`GET /admin/trace/{trace_id}` endpoint** | 1 | M | Low | The single most useful debugging tool. Given any anomaly, reconstruct the full operation. |
| 8 | **Wire `process_image_pipeline` to orchestrator** | 1 | M | Med | Validates new pattern on highest-volume task. Captures full request/response context. |
| 9 | **Wire vision API + `generate_image` + `edit_image` to orchestrator** | 1 | M | Med | Vision API is an inline HTTP route (not Celery) — eliminates C1 race. Generate/edit validate fal.ai provider cost capture. |
| 10 | **Operations Monitor page** (frontend) | 1 | L | Low | Search by trace_id/job_id/image_id. Detail view shows request, response, billing, logs. The "front-end to the system database." |

---

## ARCHITECTURE PRINCIPLES

### 1. Never auto-retry billed operations

Retrying a billed operation is fundamentally unsafe: you pay the provider again, and if all retries fail, you've spent money with nothing to deliver to the user. The only correct pattern:

- **All billed tasks:** `acks_late=False, max_retries=0, reject_on_worker_lost=False`
- **On failure:** Set Job.status=FAILED with error message. User sees "Failed" in UI and can retry manually.
- **Idempotency keys:** Defense-in-depth for edge cases (Celery visibility timeout, broker redelivery), NOT the primary retry mechanism.

This simplifies the entire architecture: you don't need complex state machines for retry recovery, you don't need to cache provider results for replay, and the billing path becomes straightforward: one decision, one provider call, one charge. If any step fails, the whole operation fails and no money moves.

### 2. Don't leave write_log() as the billing trigger

When implementing the orchestrator, there's a temptation to keep `write_log()` triggering billing and just "add CostDecision on top." **Don't do this.** That creates two billing paths running in parallel, which is harder to debug than one.

The fundamental inversion: **the task/route code owns the billing lifecycle, and logging becomes passive.** Use a feature flag per-operation to migrate incrementally:

```python
# Phase 1: feature flag controls which path is active
if operation in ORCHESTRATOR_ENABLED_OPS:
    # New path: task creates decision, calls provider, records actual
    # write_log() is passive (no billing trigger)
else:
    # Legacy path: write_log() triggers billing as side-effect
```

Start with pipeline + generate/edit (highest volume, highest cost). Leave low-volume paths (summarize, evaluate) for later. Each migration is independently testable and reversible.

### 3. The trace_id is the system's memory

Every operation that touches a provider API gets a `trace_id`. This single GUID links:
- What the user requested (request_snapshot)
- What we estimated it would cost (CostDecision)
- What the provider actually did (response_snapshot)
- What we charged (UsageRecord + BalanceTransaction)
- What happened along the way (PipelineLog entries)

When something goes wrong — a cost mismatch, a failed operation, a user complaint — you start with the `trace_id` and everything is one query away. No timestamp archaeology, no cross-referencing multiple tables by hand, no guessing.

The trace_id is not just a debugging tool — it's the foundation for automated monitoring. The Operations Monitor queries `cost_decisions` to surface anomalies (high deltas, failures, catalog misses) and lets you drill into any single trace to see the full story.
