# Observability Architecture Review — Cura AI

*Internal design review document. February 2026. Revised with implementation feedback and second-pass audit (Feb 27).*

---

## Table of Contents

- [A) System Map (As-Is)](#a-system-map-as-is)
- [B) Execution Model & Data Model](#b-execution-model--data-model)
- [C) Current Observability State](#c-current-observability-state)
- [D) Telemetry Surfaces & What to Instrument](#d-telemetry-surfaces--what-to-instrument)
- [D.1) Golden Metrics — First 10 Must-Haves](#d1-golden-metrics--first-10-must-haves)
- [E) Correlation & Schema Proposal](#e-correlation--schema-proposal)
- [F) Tooling Decision Frame](#f-tooling-decision-frame)
- [G) Phased Rollout Plan](#g-phased-rollout-plan)
- [H) Risks / Gaps / Open Questions](#h-risks--gaps--open-questions)
- [I) Privacy Model — Per-User Telemetry Toggle](#i-privacy-model--per-user-telemetry-toggle)

---

## A) System Map (As-Is)

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│ BROWSER (Next.js 14 / React 18)                                        │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌─────────────────────────┐ │
│  │ AuthCtx  │  │ UploadCtx│  │ ThemeCtx  │  │ TanStack Query (polling)│ │
│  └────┬─────┘  └────┬─────┘  └───────────┘  └───────────┬─────────────┘ │
│       │              │                                   │               │
│       └──────────────┼───────────────────────────────────┘               │
│                      │ Axios (JWT Bearer)                                │
└──────────────────────┼───────────────────────────────────────────────────┘
                       │ HTTPS
┌──────────────────────┼───────────────────────────────────────────────────┐
│ FASTAPI (backend)    ▼                                                   │
│  ┌────────────────────────────────────────────────────────────────┐      │
│  │ API Routes: auth, images, folders, clusters, search, jobs,    │      │
│  │   settings, generation, billing, vision, edit, logs           │      │
│  └─────────┬───────────────┬────────────────────┬────────────────┘      │
│            │               │                    │                        │
│  ┌─────────▼──┐  ┌────────▼──────┐  ┌──────────▼─────────┐             │
│  │ Services   │  │ Providers     │  │ BillingOrchestrator │             │
│  │ (per-user) │  │ (OpenAI,      │  │ (CostDecision →    │             │
│  │            │  │  Anthropic,   │  │  Reserve → Execute  │             │
│  │            │  │  fal.ai)      │  │  → Charge)          │             │
│  └─────┬──┬──┘  └──────┬────────┘  └─────────────────────┘             │
│        │  │             │                                                │
└────────┼──┼─────────────┼────────────────────────────────────────────────┘
         │  │             │
   ┌─────▼──▼──┐    ┌────▼──────────┐
   │ PostgreSQL │    │ Redis         │
   │ (pgvector) │    │ db0: cache    │
   │            │    │ db1: broker   │
   │ Tables:    │    │ db2: results  │
   │  images    │    └──────┬────────┘
   │  jobs      │           │
   │  pipeline_ │    ┌──────▼──────────────────────────────────────┐
   │    logs    │    │ CELERY WORKERS                               │
   │  usage_    │    │  ┌──────────────┐ ┌────────────┐ ┌────────┐│
   │    records │    │  │ default (C=1)│ │clustering  │ │gen (C=2││
   │  cost_     │    │  │ ingest, tag, │ │(C=2)       │ │train,  ││
   │    decisions│   │  │ describe,    │ │cluster,    │ │generate││
   │  ...       │    │  │ embed, del   │ │summarize,  │ │edit,   ││
   └────────────┘    │  │              │ │batch_reproc│ │evaluate││
                     │  └──────────────┘ └────────────┘ └────────┘│
   ┌────────────┐    └─────────────────────────────────────────────┘
   │ Blob Store │           │
   │ (local/    │◄──────────┘  (thumbnails, originals,
   │  Azure/S3) │               generated images, LoRA weights)
   └────────────┘

   ┌────────────────────────────────────────────┐
   │ EXTERNAL PROVIDERS                          │
   │  OpenAI  (tag, describe, embed)             │
   │  Anthropic (vision/summarization)           │
   │  fal.ai  (train LoRA, generate, edit,       │
   │           evaluate; uses OpenRouter/Grok)    │
   └────────────────────────────────────────────┘
```

### Tech Stack Inventory

| Layer | Technology | Version/Detail |
|---|---|---|
| Frontend | Next.js / React | 14.1.0 / 18.2.0 |
| HTTP client | Axios | 1.6.5 |
| State | TanStack Query | 5.17.9 |
| Toasts | Sonner | 2.0.7 |
| Backend | FastAPI / Uvicorn | Python 3.11 |
| Job runner | Celery | with Redis broker |
| Broker/cache | Redis 7 | 3 DBs (cache/broker/results) |
| Database | PostgreSQL 16 + pgvector 0.7 | 1536-dim embeddings |
| Object storage | Local FS / Azure Blob / S3 | Abstracted via `storage.py` |
| AI providers | OpenAI, Anthropic, fal.ai | Vision, embeddings, generation |
| Auth | JWT (python-jose + bcrypt) | 30min access / 7d refresh |
| IaC | Terraform | Azure Container Apps |
| CI/CD | GitHub Actions | deploy-dev.yml, deploy-prod.yml |

### Key User Journeys

1. **Upload → Process → View**: Select files → UploadContext chunks (15/batch, 3 concurrent) → backend `fast_ingest()` → `process_ingest` Celery task → thumbnail gen → `tag_image` → `describe_image` → `embed_image` → user views in gallery
2. **Cluster → Summarize → Explore**: Trigger cluster → `cluster_all_images` (HDBSCAN/KMeans) → `summarize_clusters` → view cluster detail
3. **Train → Generate → Evaluate**: Select folder/cluster → `train_lora` (fal.ai, minutes-to-hours) → `generate_image` → `evaluate_lora` (reference+creative pairs)
4. **Search**: Hybrid semantic (pgvector cosine) + text (tsvector) search with adaptive weighting
5. **Edit**: Source image → `edit_image` via fal.ai (6 edit models) → view result

---

## B) Execution Model & Data Model

### Synchronous vs Async Paths

| Path | Sync/Async | Where |
|---|---|---|
| Auth (login, register, refresh) | Sync HTTP response | `api/auth.py` |
| File serving (thumbnails, originals) | Sync HTTP (302 redirect for Azure) | `api/images.py`, `api/generation.py` |
| Image upload (chunked) | Sync HTTP per chunk → async ingest jobs | `api/images.py` → `process_ingest` task |
| Tag / Describe / Embed / Cluster | Sync HTTP (creates Job) → async Celery | `api/jobs.py` triggers → `workers/tasks.py` |
| Train / Generate / Edit | Sync HTTP (creates Job) → async Celery | `api/generation.py` → `workers/generation_tasks.py` |
| Search | Sync HTTP | `api/search.py` |
| Billing estimates | Sync HTTP | `api/billing.py` |

### Job Lifecycle

```
POST /api/jobs/...  ──►  Job(PENDING)  ──►  Celery task dispatched
                                                    │
                                              task picks up
                                                    │
                                              Job(RUNNING)
                                              set_billing_user()
                                              set_billing_job()
                                              init_trace()
                                                    │
                                         ┌──────────┼──────────┐
                                         │          │          │
                                    Provider     write_log   _update_
                                    API call     (DB)        job_status
                                         │          │          │
                                         └──────────┼──────────┘
                                                    │
                                         ┌──────────┴──────────┐
                                         │                     │
                                   Job(COMPLETED)        Job(FAILED)
                                   finalize_job_         error_message set
                                   billing()             write_log(ERROR)
                                         │
                                   finally: clear context
```

### Where State Lives

| Data | Location | Table/Key |
|---|---|---|
| Job status & progress | PostgreSQL | `jobs` (status, progress, total_items, error_message) |
| Task delivery state | Redis db1 | Celery broker messages |
| Task return values | Redis db2 | Celery result backend (24h TTL) |
| Structured task/API logs | PostgreSQL | `pipeline_logs` (category, level, trace_id, duration_ms, tokens) |
| Billing decisions | PostgreSQL | `cost_decisions` (status, estimated/actual costs, trace_id) |
| Usage records | PostgreSQL | `usage_records` (provider, model, tokens, costs, detail JSON) |
| Image files | Blob storage | `storage/` or Azure Blob `images` container |
| Frontend job awareness | Browser polling | TanStack Query `['jobs']` every 5s |
| Upload progress | Browser memory | `UploadContext` state + Sonner toast |
| Optimistic deletes | Browser sessionStorage | `'deleting-folders'` key |

### Source of Truth for Job Status

The **PostgreSQL `jobs` table** is the single source of truth. The frontend polls `GET /api/jobs?limit=50` every 5s via `useJobNotifications` hook (`frontend/src/hooks/useJobNotifications.ts:46`). Status change detection compares against a `statusMapRef` in-memory.

---

## C) Current Observability State

### Logging

| Aspect | Status | Detail |
|---|---|---|
| Library | stdlib `logging` | No structlog, no JSON formatter |
| Format | Semi-structured plain text | `%(asctime)s - %(name)s - %(levelname)s - [trace=%(trace_id)s] %(message)s` |
| Output | stdout only | Docker logs → Azure Log Analytics (if configured) |
| Trace ID injection | **Yes** | `TraceIdFilter` in `billing_context.py:116-121`, applied globally |
| DB-backed structured logs | **Yes** | `pipeline_logs` table via `write_log()` in `log_service.py` |
| Request logging middleware | **No** | No request/response logging at FastAPI level |
| Frontend logging | **No** | Only 2 `console.error()` calls in upload error path |

**What is logged well:**
- Provider API calls: provider, model, operation, duration_ms, input/output tokens, cost, success/failure (`log_service.py:36-104`)
- Task lifecycle: start, complete, fail with duration and error details
- Billing decisions: trace_id, operation, estimated vs actual costs
- AUDIT-level provider logs: `OPENAI_AUDIT`, `ANTHROPIC_AUDIT` with full request/response detail
- **Upload chunks** (recently added): per-chunk `write_log()` with file counts, new/dup/fail breakdown, and duration_ms (`api/images.py`)

**What is NOT logged:**
- HTTP request/response (no middleware) — latency, status codes, payload sizes
- Database query timing
- Redis operations
- File download / serving operations (thumbnails, originals, generated images)
- Frontend errors, user actions, page views

### Recently Implemented: Upload Pipeline Observability

The following was added in February 2026 and addresses several gaps from the original review:

**Backend (`api/images.py`, `workers/tasks.py`, `services/image_service.py`):**

- **Chunk-level timing + counters in `Job.result` JSON** (no migration needed):
  ```json
  {
    "first_chunk_at": "2026-02-27T14:30:01.123",
    "last_chunk_at": "2026-02-27T14:30:05.678",
    "processing_done_at": "2026-02-27T14:30:12.345",
    "total_received": 200,
    "new_count": 180, "duplicate_count": 15, "failed_count": 5,
    "chunks_received": 14,
    "chunk_timings": [{"chunk_idx": 0, "n_files": 15, "n_new": 13, "n_dup": 1, "n_fail": 1, "api_ms": 1234}]
  }
  ```
- **`with_for_update()` row lock** on `job.result` merge — serializes parallel chunk writers, fixing the race condition where concurrent chunks overwrote each other's `image_ids`. Uses `lazyload(Job.image)` to avoid PostgreSQL's "FOR UPDATE cannot be applied to nullable side of outer join" error (see [H.9](#h9-lazyload-pattern)).
- **`processing_done_at` timestamp** stamped in `job.result` when Celery finalizes the job — enables upload-phase vs processing-phase duration breakdown.
- **`started_at` set on INGEST job creation** (was previously missing).
- **Per-chunk `write_log()`** call with chunk index, file counts, and duration.
- **Re-delivery guard fix**: `_finish_ingest_job_item()` now called on skipped re-delivered images (prevents jobs from hanging forever after worker restart).
- **`IntegrityError` handling in `fast_ingest()`**: gracefully returns `None` (duplicate) instead of 500 error on concurrent duplicate uploads.
- **Deferred PIL metadata**: `compute_image_metadata()` removed from `fast_ingest()` — dimensions and phash are computed by the Celery worker. Saves ~20-50ms per file in the HTTP handler.

**Frontend (`jobs/page.tsx`, `utils.ts`, `images/page.tsx`, `UploadContext.tsx`, `useJobNotifications.ts`):**

- **Duration on job progress bar**: completed jobs show elapsed time (e.g., "50/50 · 12s").
- **`IngestSummaryPill`**: INGEST jobs show "200 received" pill with hover tooltip ("180 new, 15 dup, 5 failed").
- **`min_status: 'ingested'` filter on Unfiled query**: PENDING images (no thumbnails) are hidden from the UI.
- **Cache invalidation fix**: `UploadContext` and `useJobNotifications` now also invalidate `['unfiled-images']` and `['all-images']` query keys (previously only `['images']` was invalidated, which didn't match `ImageGrid`'s prefixed keys).

### Metrics

| Aspect | Status | Detail |
|---|---|---|
| Prometheus/StatsD | **None** | No metrics library in dependencies |
| Custom metrics endpoint | Admin-only `/api/admin/metrics` | Computes at query time from DB: ops/hour, failure rate, cost/op |
| Infrastructure metrics | Implicit via Azure Monitor | Container Apps → Log Analytics workspace |

**Important distinction:** The admin `/api/admin/metrics` endpoint is a **reporting page**, not a monitoring system. It queries the database on demand and computes aggregates at read time. It is not real-time, not cheap (full table scans), and cannot detect infrastructure or queue issues early. It should be kept for admin UX, but must not be treated as a substitute for actual metrics collection (counters, histograms, gauges emitted at write time and scraped by a collector).

### Tracing

| Aspect | Status | Detail |
|---|---|---|
| OpenTelemetry | **Not installed** | No OTel SDK in pyproject.toml |
| Distributed tracing | **None** | No span propagation between services |
| Correlation ID | **Partial** | `trace_id` (UUID hex) generated per task via `init_trace()` |
| Scope of trace_id | Worker tasks only | Not generated for sync API requests (except vision/generation endpoints) |
| Cross-service propagation | **None** | No trace context in Celery task headers |
| Frontend → Backend | **None** | No request ID or correlation header sent from browser |

**Critical gap:** `trace_id` is generated inside Celery tasks but NOT for most API endpoints. There is no middleware to generate a request ID for every HTTP request. The `init_trace()` call appears in:
- `tasks.py` task functions (per-task)
- `api/vision.py:235` (vision endpoint)
- `api/generation.py:398` (generation endpoint)
- NOT in other API routes (images, folders, clusters, search, etc.)

### Frontend Telemetry

| Aspect | Status |
|---|---|
| Error tracking (Sentry etc.) | **None** |
| Error boundaries | **None** (no `error.tsx` or `global-error.tsx`) |
| Analytics | **None** (no GA, Mixpanel, PostHog, Amplitude) |
| Web Vitals / RUM | **None** |
| Session replay | **None** |
| Performance monitoring | **None** |
| Unhandled rejection handler | **None** |

All user-facing error feedback is through ephemeral Sonner toasts (128+ `toast.error()` calls across the codebase).

### Alerting

| Aspect | Status |
|---|---|
| Alert rules | **None defined** |
| Dashboards | Admin-only in-app: MetricsView (30s polling), OperationsMonitor, ReconciliationView, AnomaliesView |
| SLOs | **None** |
| On-call hooks | **None** |
| Azure Monitor alerts | **Not configured** in Terraform |

### Sampling / PII

| Aspect | Status |
|---|---|
| PII in logs | `user_id` (integer) stored in logs — not hashed. Email in auth logs. **This is fine for now (no real users).** |
| Image data in logs | Provider AUDIT logs include `image_bytes` size and `prompt_text_len` — no raw image data in logs, but full prompts are stored. |
| Sampling | No sampling — all events logged |
| Log retention | `cleanup_old_pipeline_logs` Celery beat task runs daily |
| Privacy controls | **None currently.** Per-user `telemetry_private` toggle planned for pre-launch. See [Section I: Privacy Model](#i-privacy-model--per-user-telemetry-toggle). |

---

## D) Telemetry Surfaces & What to Instrument

### Frontend

| Surface | File | What to Capture |
|---|---|---|
| Route transitions | `layout.tsx` (router) | Page views, navigation timing, referrer |
| Upload UX | `contexts/UploadContext.tsx` | Files selected, chunk progress, failures per chunk, total duration, retry count |
| Progress polling | `hooks/useJobNotifications.ts:46` | Poll count, status transitions seen, time-to-completion per job type |
| API errors | `lib/api.ts:93-157` | Error code, endpoint, response time, retry attempts, token refresh cycles |
| Auth flow | `contexts/AuthContext.tsx` | Login/register attempts, token refresh failures, session duration |
| Search | `app/search/page.tsx` | Query terms (hashed), result count, click-through, latency |
| Generate/Train | `app/generate/page.tsx`, `app/models/` | Form fill time, parameter choices, generation wait time perceived |
| Web Vitals | Not yet instrumented | LCP, FID, CLS, TTFB, INP |
| Unhandled errors | No handler exists | `window.onerror`, unhandled promise rejections |

### Backend API

| Surface | File | What to Capture |
|---|---|---|
| Request middleware | `main.py` (missing) | request_id, method, path, status_code, duration_ms, user_id, content_length |
| Upload endpoint | `api/images.py` | Files per request, total bytes, chunk index, upload duration |
| Provider wrappers | `providers/openai_provider.py`, `anthropic_provider.py`, `fal_provider.py` | Already logging duration/tokens/cost — add histograms |
| DB queries | `db/base.py` | Query count per request, slow queries (>100ms) |
| Auth | `core/security.py` | Failed auth attempts, token refresh rate |
| File serving | `api/images.py` (thumbnails), `api/generation.py` | Serve latency, cache hit rate, SAS URL generation time |
| Billing | `services/billing_orchestrator.py` | Reserve time, charge time, balance check failures |
| Health check | `main.py:55` | Add dependency checks (DB ping, Redis ping, storage accessible) |

### Workers

| Surface | File | What to Capture |
|---|---|---|
| Task start/end | `workers/tasks.py`, `workers/generation_tasks.py` | Already logging — add queue wait time (enqueue_time vs start_time) |
| Step timings | Within tasks (tag, describe, embed steps) | Individual step durations within pipeline tasks |
| Provider call duration | `providers/*.py` | Already captured — standardize as histogram |
| Retries | Celery config | Currently max_retries=0 everywhere — track manual retries via `/jobs/{id}/retry` |
| Idempotency | `billing_context.py:103-113` | Idempotency key hits (dedup detections) |
| Queue depth | Redis | Pending message count per queue (default, clustering, generation) |
| Worker utilization | Celery | Active tasks / concurrency, prefetch count |
| Training duration | `generation_tasks.py` | fal.ai polling loop duration, polling iterations, timeout |
| Cancellation | `generation_tasks.py` | Cancel check frequency, cancel-to-stop latency |

### Storage / DB / Queue

| Surface | Where | What to Capture |
|---|---|---|
| Queue backlog | Redis db1 | `LLEN` on each queue: default, clustering, generation |
| Dead letters | Redis | Tasks that fail after max_retries (currently 0 = no DLQ scenario, tasks just fail) |
| Blob upload/download | `services/storage.py` | Duration, bytes, errors, SAS generation time |
| DB connection pool | `db/base.py` | Pool size, overflow, checkout time, checked-out count |
| Slow queries | SQLAlchemy events | Queries > 100ms |
| Redis latency | Celery broker | Connection timeouts, reconnects |

---

## D.1) Golden Metrics — First 10 Must-Haves

These are the concrete signals that define "Phase 0/1 is complete." Each metric should be emittable from the start and serve as the validation checklist.

| # | Subsystem | Metric | Type | Where Emitted | Phase |
|---|---|---|---|---|---|
| 1 | **API** | Request count by route | Counter | Request middleware (`main.py`) | 0 |
| 2 | **API** | Request latency p50/p95/p99 by route | Histogram | Request middleware (`main.py`) | 0 |
| 3 | **API** | Error rate by route (4xx, 5xx) | Counter | Request middleware (`main.py`) | 0 |
| 4 | **Upload** | Bytes uploaded per chunk, upload duration, failure rate | Counter + Histogram | `api/images.py` upload endpoint + `UploadContext.tsx` | 0 |
| 5 | **Queue** | Queue depth per queue (default, clustering, generation) | Gauge | Celery beat task or Flower (`LLEN` on Redis) | 1 |
| 6 | **Queue** | Queue wait time p95 per queue | Histogram | `started_at - created_at` on Job table | 1 |
| 7 | **Workers** | Task duration per task type | Histogram | `workers/tasks.py`, `workers/generation_tasks.py` (already captured in `write_log` — expose as metric) | 1 |
| 8 | **Workers** | Task failure rate per task type | Counter | `_update_job_status(FAILED)` calls | 1 |
| 9 | **Providers** | Call duration + error rate + rate-limit count per provider/model | Histogram + Counter | `providers/openai_provider.py`, `anthropic_provider.py`, `fal_provider.py` (already timed — expose as metric) | 1 |
| 10 | **Providers** | Token counts + cost totals per provider/model/operation | Counter | `write_log()` calls with `input_tokens`/`output_tokens`/`provider_cost` | 1 |

**Bonus (add in Phase 1):**
- **DB**: Slow query count (queries > 100ms) — SQLAlchemy event hooks
- **DB**: Connection pool saturation (checked-out / pool_size) — SQLAlchemy pool events

These 10 metrics answer the most common incident questions: "Is the API slow?", "Is the queue backed up?", "Are providers failing?", "How much are we spending?"

---

## E) Correlation & Schema Proposal

### Identifiers to Standardize

**Key design decision: `trace_id` and `request_id` are separate concepts from day 1.**

- **`trace_id`** = the distributed trace. It ties together a browser action → API request → Celery task → provider calls. A single trace can span multiple services and multiple request_ids.
- **`request_id`** = per-service, per-HTTP-request identifier. Each API call gets its own request_id. Useful for log grep within a single service.

The trace_id is what you follow end-to-end. The request_id is what you grep for within backend logs. Both exist on every log line.

| ID | Scope | Generated Where | Propagation | Current Status |
|---|---|---|---|---|
| `trace_id` | Distributed (cross-service) | API middleware (NEW) or `init_trace()` in tasks | Sent to Celery via task kwargs, stored in pipeline_logs, cost_decisions, usage_records | **Exists** but only in workers + 2 API endpoints. Must be generated in middleware for all requests. |
| `request_id` | Per-HTTP-request | API middleware (NEW) | Logged locally, returned in `X-Request-Id` response header | **Does not exist** — must add middleware |
| `session_id` | Browser session | Frontend localStorage (NEW) | Sent as `X-Session-Id` header on every Axios request | **Does not exist** |
| `user_id` | Auth scope | JWT decode | All logs, all DB queries | **Exists** — integer, stored raw (see [Privacy Model](#i-privacy-model--per-user-telemetry-toggle) for future redaction) |
| `job_id` | Job scope | `Job` table PK | Task context, logs, billing | **Exists** and well-propagated |
| `upload_id` | Upload batch scope | Frontend per-upload (NEW) | Groups all chunks of one upload operation | **Does not exist** |
| `celery_task_id` | Task scope | Celery auto-generated | Job table, Celery result backend | **Exists** in `Job.celery_task_id` |
| `provider_request_id` | Provider call scope | Provider response | Logged for fal.ai (`request_id`), not for OpenAI/Anthropic | **Partial** |

### Proposed Propagation

```
Browser                          API                            Worker
───────                          ───                            ──────
session_id (localStorage UUID)
    │
    ├─► X-Session-Id header ──► middleware extracts
    │                           generates trace_id (UUID)
    │                           generates request_id (UUID)
    │                           sets both in context (billing_context)
    │                           logs: {trace_id, request_id, session_id, user_id, path, method}
    │                               │
    │                               ├─► Celery task kwargs: {trace_id: trace_id}
    │                               │       │
    │                               │       ├─► set_trace_id(passed_trace_id)
    │                               │       │   (uses API's trace_id, NOT a new one)
    │                               │       │
    │                               │       ├─► write_log(): {trace_id, job_id, user_id, image_id}
    │                               │       │
    │                               │       └─► BillingOrchestrator: {trace_id, job_id}
    │                               │
    │                               └─► Response headers:
    │                                     X-Request-Id: <request_id>
    │                                     X-Trace-Id: <trace_id>
    │
    └─► Frontend logs: {session_id, trace_id (from response), action, duration_ms}
```

**Why both?** When debugging "upload felt slow," you follow the `trace_id` from browser → API → all spawned ingest tasks → provider calls. When debugging "this one API response was wrong," you grep the `request_id` in backend logs. They serve different scopes, and conflating them early creates confusion when a single trace spans multiple API calls (e.g., the upload flow makes multiple chunk requests, each with its own request_id but sharing a user session).

### Canonical Event Schema

```json
{
  "ts": "2026-02-27T14:30:00.123Z",
  "level": "info",
  "component": "api|worker|frontend",
  "service": "backend|celery-default|celery-clustering|celery-generation|frontend",
  "action": "http.request|task.start|task.complete|provider.call|upload.chunk|...",

  "trace_id": "abc123...",
  "request_id": "def456...",
  "session_id": "ghi789...",
  "user_id": 1,
  "job_id": 42,
  "image_id": 100,

  "duration_ms": 1234,
  "status_code": 200,
  "bytes_in": 0,
  "bytes_out": 4096,

  "provider": "openai|anthropic|fal",
  "model": "gpt-4o|claude-sonnet|flux-dev",
  "operation": "tag|describe|embed|generate|edit|train|evaluate",
  "input_tokens": 500,
  "output_tokens": 150,
  "cost_estimated_sparks": 120,
  "cost_actual_sparks": 115,

  "error_code": null,
  "error_message": null,
  "retry_count": 0,

  "queue": "default|clustering|generation",
  "queue_wait_ms": 45,

  "telemetry_private": false
}
```

**Note on `user_id` and privacy:** Currently, `user_id` is stored as a raw integer in all telemetry. No hashing or redaction is applied. This is intentional — we have no real users yet and need full visibility for debugging. When real users are onboarded, the per-user privacy toggle (`telemetry_private` flag on User model) will control whether telemetry for that user includes raw identifiers, prompts, filenames, etc. See [Section I: Privacy Model](#i-privacy-model--per-user-telemetry-toggle) for the full design.

---

## F) Tooling Decision Frame

### Required Capabilities

| Capability | Priority | Rationale |
|---|---|---|
| **Error tracking** (frontend + backend) | Must-have | No error visibility today. Unhandled rejections, React errors, API 500s all invisible. |
| **Distributed tracing** (API → worker → provider) | Must-have | Cannot trace a user action end-to-end today. |
| **Structured logging** (search + filter) | Must-have | Plain text stdout logs are unsearchable at scale. |
| **Request-level metrics** (latency, error rate) | Must-have | No HTTP-level observability exists. |
| **Queue metrics** (depth, wait time, throughput) | Must-have | No visibility into worker backlogs. |
| **RUM + Web Vitals** | Nice-to-have | Users may experience slow page loads but we wouldn't know. |
| **Session replay** | Nice-to-have | Useful for debugging UX issues but privacy-sensitive with image data. |
| **SLOs + alerting** | Must-have (Phase 3) | No alerts means silent failures. |
| **Cost dashboards** | Nice-to-have | Admin billing views exist but need provider-level cost trends. |
| **Anomaly detection** | Nice-to-have | AnomaliesView exists in-app but basic. |

### Integration Constraints

| Constraint | Detail |
|---|---|
| Python 3.12 backend | Good OTel support, Sentry SDK support |
| Celery workers | Requires Celery-specific instrumentation (task signals, context propagation) |
| Next.js 14 (Pages/App Router) | Good SDK support from most vendors |
| Azure Container Apps | Log Analytics workspace already provisioned; Application Insights available |
| Redis broker | Celery Flower or Redis Exporter for queue metrics |
| Image data sensitivity | No raw images in telemetry. Currently no PII restrictions (no real users). Per-user `telemetry_private` toggle planned pre-launch — see [Section I](#i-privacy-model--per-user-telemetry-toggle). |
| Small team / low ops overhead | Managed services preferred over self-hosted |

### Three Viable Architectures

#### Option 1: OpenTelemetry-First (Collector + Pluggable Backends)

```
Frontend ──► OTel JS SDK ──► OTel Collector ──► Backend(s)
Backend  ──► OTel Python SDK ──►      ↑
Workers  ──► OTel Python SDK ──►      │
                                      ▼
                              Jaeger / Grafana Tempo (traces)
                              Prometheus / Grafana Mimir (metrics)
                              Loki / Elasticsearch (logs)
```

| Pros | Cons |
|---|---|
| Vendor-neutral, swap backends freely | Higher setup complexity (collector, multiple backends) |
| Full context propagation via W3C trace context | Self-hosted = ops burden unless using Grafana Cloud |
| Auto-instrumentation for FastAPI, SQLAlchemy, Redis, Celery | Need to wire Celery context propagation manually |
| Community standard, long-term investment | No built-in session replay or RUM |

**Best if:** You want maximum flexibility and plan to scale to multiple environments.

#### Option 2: All-in-One Vendor Suite

Examples: Datadog, New Relic, Dynatrace, Elastic APM, Azure Application Insights

```
Frontend ──► Vendor RUM SDK ──► Vendor Cloud
Backend  ──► Vendor APM SDK ──►     ↑
Workers  ──► Vendor APM SDK ──►     │
                                    ▼
                         Unified traces/metrics/logs/RUM dashboard
```

| Pros | Cons |
|---|---|
| Single pane of glass | Vendor lock-in |
| Auto-instrumentation for everything | Cost scales with data volume (can be expensive) |
| Built-in alerting, SLOs, anomaly detection | May include features you don't need |
| Session replay (Datadog, LogRocket) | Privacy concerns with image app |
| Fastest time-to-value | Azure App Insights is free-tier-friendly but less capable for distributed tracing |

**Azure Application Insights specific note:** Already have a Log Analytics workspace in Terraform (`infra/modules/container_apps/main.tf`). Adding App Insights would be low-friction but gives limited Celery support.

**Best if:** You want fast setup and are willing to pay for convenience.

#### Option 3: Best-of-Breed (Composable) — Recommended

```
Frontend ──► Sentry (errors) + PostHog (analytics/replay) ──► respective clouds
Backend  ──► Sentry (errors) + OTel (traces/metrics) ──► Grafana Cloud / Azure Monitor
Workers  ──► Sentry (errors) + OTel (traces/metrics) ──►         ↑
Queue    ──► Celery Flower / Redis Exporter ──► Prometheus ──►    │
```

| Pros | Cons |
|---|---|
| Best tool for each job | Multiple dashboards to check |
| Sentry: excellent error grouping, stack traces, Celery integration | More SDKs to maintain |
| PostHog: open-source, self-hostable, session replay + analytics | Integration between tools is manual |
| Grafana Cloud: free tier generous for small apps | Correlation across tools requires shared trace_id |
| Cost-effective at small scale | |

### Recommendation

**Option 3 (Best-of-Breed) with OpenTelemetry as the backbone from day 1.**

The key architectural decision: **OTel is the spine, not an add-on.** Even if we pick Sentry or Azure Monitor as the initial backend, having OTel semantics (trace context, spans, W3C propagation) from the start prevents "we can't correlate across workers" pain later. The system already has multiple components (Next.js + FastAPI + Celery + providers) and async boundaries — exactly where you need distributed tracing.

Concrete tooling:

- **OpenTelemetry Python SDK** as the tracing/metrics backbone — auto-instrument FastAPI, SQLAlchemy, Redis; manual spans on provider calls and Celery tasks. Export initially to Sentry (which supports OTel ingestion) or Azure Monitor.
- **Sentry** for error tracking (frontend + backend + Celery) — immediate value, excellent Python/Next.js support, free tier covers small apps. Sentry also provides basic performance/tracing which overlaps with OTel — use OTel as the source of truth, Sentry as the error-first view.
- **RUM/analytics**: Postpone until Phase 2. Add PostHog (or similar) once correlation + errors are solid and we know what questions we're trying to answer.
- **Existing Azure Log Analytics** for infrastructure logs (already provisioned).
- **Celery Flower** or Redis metrics exporter for queue observability.

This avoids vendor lock-in, keeps costs low, and the OTel foundation means we can swap backends (Grafana Cloud, Datadog, etc.) without re-instrumenting code.

---

## G) Phased Rollout Plan

### Phase 0: Correlation + Error Capture (do this first, ~1 week)

**Goal:** Every request and task gets correlation IDs. Errors are captured. This alone reveals 80% of pain in week one.

This is the highest-leverage work. Everything else builds on it.

| # | Task | Detail | Files Touched | Risk |
|---|---|---|---|---|
| 0.1 | **FastAPI request middleware** | Generate `trace_id` (UUID) + `request_id` (UUID) per request. Set both in `billing_context`. Log request summary: `{trace_id, request_id, method, path, status, duration_ms, user_id}`. Return `X-Trace-Id` + `X-Request-Id` response headers. | `main.py`, `billing_context.py` | Low |
| 0.2 | **Frontend `session_id`** | Generate UUID in `localStorage` on first visit. Send as `X-Session-Id` header on every Axios request. | `lib/api.ts` | Low |
| 0.3 | **Frontend `trace_id` capture** | Read `X-Trace-Id` from API responses in Axios interceptor. Attach to Sentry breadcrumbs/scope. | `lib/api.ts` | Low |
| 0.4 | **Install Sentry (backend)** | `pip install sentry-sdk[fastapi,celery]`. Initialize in `main.py` startup. Tag events with `trace_id`, `request_id`, `job_id`, `user_id`. Configure `traces_sample_rate=0.2`, `send_default_pii=True` (no real users yet — see Privacy Model). | `main.py`, `pyproject.toml` | Low |
| 0.5 | **Install Sentry (frontend)** | `npm install @sentry/nextjs`. Add `sentry.client.config.ts`. Configure with `session_id` tag. | `frontend/package.json`, new sentry config files | Low |
| 0.6 | **Add `global-error.tsx` and `error.tsx`** | Next.js error boundaries to catch React rendering errors. Report to Sentry. | `frontend/src/app/error.tsx`, `frontend/src/app/global-error.tsx` | Low |
| 0.7 | **Upgrade health check** | `GET /health` checks: DB (`SELECT 1`), Redis ping, storage accessible. Return degraded status per-dep. | `main.py` | Low |

**Expected outcome:** You can grep any error in Sentry → find `trace_id` → grep backend logs for that trace → see the full request → see which Celery task it spawned. Health checks actually verify dependencies.

**Validation:** After this phase, you should be able to answer: "What was the request that triggered this error?" for any backend or frontend error.

### Phase 1: Distributed Tracing + Worker Correlation + Queue Visibility (2-3 weeks)

**Goal:** Trace a user action end-to-end: browser → API → Celery task → provider call. Queue health visible.

| # | Task | Detail | Files Touched | Risk |
|---|---|---|---|---|
| 1.1 | **Pass `trace_id` to Celery tasks** | When API dispatches a Celery task, include `trace_id` in task kwargs. In the task, call `set_trace_id(passed_trace_id)` instead of `init_trace()`. If no trace_id passed (e.g., beat tasks), generate a new one. | All `.apply_async()` call sites, `tasks.py`, `generation_tasks.py` | Low |
| 1.2 | **Pass `session_id` + `job_id` to Celery tasks** | Include both in task kwargs so they appear in all downstream logs and Sentry events. | Same as 1.1 | Low |
| 1.3 | **Install OpenTelemetry Python SDK** | `opentelemetry-sdk`, auto-instrumentation for FastAPI, SQLAlchemy, Redis. Export to Sentry (OTel ingestion) initially. | `pyproject.toml`, `main.py`, `celery_app.py` | Medium — test overhead |
| 1.4 | **Instrument provider calls as OTel spans** | Wrap OpenAI/Anthropic/fal.ai calls with spans. Attach attributes: provider, model, operation, tokens, cost. Providers already have timing — wrap it. | `providers/openai_provider.py`, `providers/anthropic_provider.py`, `providers/fal_provider.py` | Low |
| 1.5 | **Add queue depth monitoring** | Celery beat task (every 60s): `LLEN` on default, clustering, generation queues. Log as structured event. | `workers/tasks.py` (new beat task) | Low |
| 1.6 | **Add queue wait time metric** | Compute `started_at - created_at` for every job. Log in `_update_job_status(RUNNING)`. | `workers/tasks.py` | Low |
| 1.7 | **Structured JSON logging** | Replace `logging.basicConfig` with JSON formatter (`python-json-logger`). Human-readable in dev (detect TTY), machine-parseable in Docker/Azure. | `main.py`, `celery_app.py` | Low |
| 1.8 | **SQLAlchemy slow query logging** | `before_cursor_execute` / `after_cursor_execute` events. Log queries > 100ms with statement (truncated) and duration. | `db/base.py` | Low |

**Expected outcome:** Click from a Sentry error → see the distributed trace → see the API request that spawned the job → see the Celery task execution → see the provider API call with tokens/cost/duration. Queue depth visible as a time series.

**Validation:** Golden metrics 1-10 from section D.1 should all be answerable after this phase.

### Phase 2: Frontend RUM + UX Funnels (2-3 weeks)

**Goal:** Understand user experience. Track funnels, performance, rage clicks.

| # | Task | Detail | Risk |
|---|---|---|---|
| 2.1 | **Web Vitals reporting** | Use `next/web-vitals` or Sentry Performance. Report LCP, FID, CLS, TTFB, INP. | Low |
| 2.2 | **Track key user funnels** | Upload: files selected → upload started → upload complete → images visible. Train: model config → train started → complete → first generation. | Low |
| 2.3 | **API request timing in frontend** | Axios interceptor: measure request duration. Tag slow requests (>2s) in Sentry. | Low |
| 2.4 | **Upload lifecycle instrumentation** | Instrument UploadContext: chunk success/failure rates, total upload time, retry attempts. Send as Sentry breadcrumbs + custom events. | Low |
| 2.5 | **Job wait time (user-perceived)** | From toast "job started" to `useJobNotifications` detecting completion → measure perceived duration. | Low |
| 2.6 | **Evaluate session replay** | Sentry Replay or PostHog. For now, no privacy masking needed (no real users). When `telemetry_private` users exist, mask image elements and redact prompts. | Medium |

**Expected outcome:** Know where users drop off, what's slow, what errors they encounter before they report them.

### Phase 3: SLOs + Alerts + Cost Dashboards (2-3 weeks)

**Goal:** Proactive monitoring. Get alerted before users complain.

| # | Task | Detail | Risk |
|---|---|---|---|
| 3.1 | **Define SLOs** | API latency p99 < 500ms (sync endpoints). Job completion rate > 95%. Upload success rate > 99%. Provider error rate < 5%. | Low |
| 3.2 | **Configure alerts** | Sentry: error rate spike, new error types. Infra: queue depth > threshold, worker crash, health check fail. Cost: daily spend anomaly. | Low |
| 3.3 | **Cost dashboard** | Extend admin MetricsView: cost trends over time, cost per provider/model, cost per user, projected monthly spend. Data already in `usage_records`. | Low |
| 3.4 | **Anomaly detection** | Build on existing AnomaliesView. Add: sudden cost spikes, unusual error patterns, queue growth trends. | Medium |
| 3.5 | **On-call runbook** | Document: how to check queue depth, restart stuck workers, recover failed jobs, check provider status, read distributed traces. | Low |

**Expected outcome:** Alerts fire before users notice problems. Cost trends are visible and projectable.

---

## H) Risks / Gaps / Open Questions

### Architectural Issues That Will Break Good Telemetry

1. **Thread-local context in async code** (`billing_context.py:6`)
   - `_ctx = threading.local()` is thread-local, not task-local. FastAPI runs async handlers on the event loop — `threading.local()` may not scope correctly when async handlers share threads. In Celery, the risk depends on the concurrency model (prefork = separate processes, so thread-locals are safe; threads/gevent/eventlet = shared, not safe).
   - **Fix:** Use `contextvars.ContextVar` instead of `threading.local()`. Python 3.11+ has full support. This is correct for both FastAPI (async-aware) and Celery prefork (each fork gets its own context).
   - **Caveat:** Celery does NOT automatically propagate `contextvars` across process boundaries. When the API dispatches a task to a worker (separate process), context is lost. You must explicitly pass `trace_id`, `session_id`, etc. as task kwargs. The `contextvars` fix helps within a single process (e.g., within a FastAPI request handler, or within a Celery task's execution), not across the API→worker boundary. Cross-process propagation requires explicit kwarg passing (Phase 1, task 1.1).

2. **trace_id not generated for most API endpoints**
   - `init_trace()` is only called inside worker tasks and 2 API endpoints (vision, generation). Most sync API calls (images CRUD, search, folders, settings) have no trace_id.
   - **Fix:** Request ID middleware (Phase 0) that calls `init_trace()` for every request.

3. **No frontend-to-backend correlation**
   - No `X-Request-Id` or `X-Session-Id` headers sent from browser. Cannot link a user action to a backend request.
   - **Fix:** Phase 0 session_id + request_id propagation.

4. **No queue wait time tracking**
   - Job `created_at` is set when the Job row is created, but `started_at` is set when the Celery task picks it up. The gap between Celery dispatch and task start (actual queue wait) is not explicitly measured.
   - **Partial workaround:** `started_at - created_at` approximates it, but includes job creation overhead.

5. **Celery task results expire in 24h** (`celery_app.py:63`)
   - After 24h, task result metadata is gone from Redis. Long-running training tasks that take hours may have their results cleaned up before inspection.
   - **Mitigation:** Job status is in PostgreSQL (durable). Redis results are secondary.

6. **No dead letter queue**
   - With `max_retries=0` on all expensive tasks, failed tasks simply fail. No DLQ for post-mortem analysis.
   - **Acceptable:** By design — expensive tasks should not auto-retry. Job table captures failures.

7. **AUDIT logs at WARNING level** (`openai_provider.py:125`)
   - Provider audit logs use `logger.warning()` with full response text. This pollutes warning-level logs and may include large payloads.
   - **Fix:** Move to DEBUG or a dedicated audit logger.

8. **Health check is trivial** (`main.py:55-58`)
   - Returns `{"status": "healthy"}` without checking any dependency. A backend with a dead DB connection would still report healthy.
   - **Fix:** Phase 0 — add DB, Redis, storage checks.

<a id="h9-lazyload-pattern"></a>
9. **`with_for_update()` requires `lazyload()` on Job model** (discovered during implementation)
   - The `Job` model has `lazy="joined"` on its `image` relationship, which generates a LEFT JOIN. PostgreSQL's `FOR UPDATE` cannot be applied to the nullable side of an outer join, causing `psycopg2.errors.FeatureNotSupported`.
   - **Fix (implemented):** Add `.options(lazyload(Job.image))` to any `with_for_update()` query on the `Job` model. This suppresses the eager join.
   - **Broader risk:** Any model with `lazy="joined"` on a nullable FK will hit this. Future `with_for_update()` usage on other models should be checked for the same pattern.

10. **TanStack Query cache invalidation is key-prefix fragile**
    - `ImageGrid` uses prefixed query keys like `['unfiled-images', filter, page]` and `['all-images', filter, page]`. Invalidating `['images']` does NOT match these — TanStack Query's `invalidateQueries` matches keys that *start with* the provided prefix.
    - **Discovered when:** Upload completed but the Unfiled section showed stale "No Preview" ghosts until hard reload.
    - **Fix (implemented):** `UploadContext` and `useJobNotifications` now also invalidate `['unfiled-images']` and `['all-images']`.
    - **Broader risk:** Any new `ImageGrid` instance with a different `queryKeyPrefix` will silently miss cache invalidations. Consider a convention: either use a shared prefix (e.g., all image queries start with `['images', ...]`) or maintain a central list of image-related query keys to invalidate.

11. **Celery task re-delivery and idempotency gaps**
    - With `acks_late=True` (Celery default) or worker crashes, tasks can be re-delivered. The re-delivery guard in `process_ingest_batch` (check `status != PENDING`) was missing a `_finish_ingest_job_item()` call, causing jobs to hang forever.
    - **Fix (implemented):** Re-delivery guard now calls `_finish_ingest_job_item(db, job_id, failed=False)` before skipping.
    - **Gap:** There is no systematic idempotency analysis per task type. Each task has its own guard pattern. A table of idempotency guarantees per task type would prevent similar bugs. Training tasks use `acks_late=False` + `max_retries=0` to avoid re-delivery entirely, but other tasks rely on application-level guards.

12. **Storage orphan files are undetectable**
    - `fast_ingest()` writes files to storage *before* creating the DB record. If the process crashes between `save_image()` and `db.flush()`, the file is orphaned — it exists in storage with no corresponding `images.object_key` reference.
    - **No cleanup mechanism exists.** No Celery beat task, no admin endpoint, no reconciliation job.
    - **Fix:** Add a periodic reconciliation task that lists storage objects and compares against `images.object_key` + `generated_images.object_key`. Delete orphans older than 1 hour. Track orphan count as a metric.

13. **`folder.image_count` denormalization drift**
    - `folder_service.py:add_images_to_folder()` computes `image_count` as `COUNT(*) + added` without row locking. Under concurrent `add_images_to_folder` calls (e.g., two uploads to the same folder), the count can drift from actual.
    - **Impact:** Displayed folder image count may be wrong. Not a data loss bug, but a UI accuracy issue.
    - **Fix:** Compute count purely from `COUNT(*)` after flushing, or use `with_for_update()` on the folder row.

14. **Frontend error swallowing in TanStack Query**
    - Many `useQuery` calls have no `onError` handler. When a query fails (e.g., network error, 500), TanStack Query silently retries 3 times then stops — the UI just shows a loading spinner forever.
    - The Axios interceptor handles 401 (token refresh) but non-401 errors in query functions are not surfaced to the user unless the component explicitly checks `isError`.
    - **Impact:** Users see infinite loading states instead of actionable error messages.
    - **Fix:** Add a global `QueryClient` `onError` handler that shows a Sonner toast for unexpected query failures. Or add `error.tsx` error boundaries per route.

15. **Default worker concurrency=1 creates ingest bottleneck**
    - `docker-compose.yml` sets `--concurrency=1` on the default Celery worker. A 100-image upload dispatches ~7 `process_ingest_batch` tasks that execute sequentially. Each task reads files from storage and generates 3 thumbnails per image.
    - **Impact:** Queue wait time for later ingest batches grows linearly. The user sees "50/50" progress but folder assignment is delayed by the sequential processing.
    - **Metric to track:** Queue wait time for the default queue (Phase 1, item 1.6). If `started_at - created_at` for ingest tasks regularly exceeds 30s, increase concurrency to 2.
    - **Caution:** Increasing concurrency increases DB connection pool pressure (currently `pool_size=5, max_overflow=5`).

16. **`min_status` filter not applied consistently across UI views**
    - The Unfiled query on `/images` now filters `min_status: 'ingested'` to hide PENDING images (no thumbnails). But other views may still show them:
      - All Images page (`/images/all`) — needs verification
      - Folder detail page (`/images/folder/[id]`) — folder assignment is deferred, so PENDING images shouldn't appear, but race conditions are possible
      - Search results — PENDING images have no embedding, so they won't appear in semantic search, but could appear in tag/text search if tags are set before status advances (unlikely but unverified)
    - **Fix:** Audit all `imagesApi.list()` call sites. Any view that renders thumbnails should filter `min_status: 'ingested'` to avoid "No Preview" states.

### What Could Not Be Determined from Code

| Unknown | Evidence Checked | Next Step |
|---|---|---|
| Azure Log Analytics retention/query configuration | Terraform module references `log_analytics_workspace_id` but no alert rules or saved queries | Check Azure portal for actual Log Analytics workspace configuration |
| Redis memory pressure / eviction policy | Docker compose uses default Redis config | Check `redis.conf` or `maxmemory-policy` in Azure Redis settings |
| Actual Azure Monitor integration | Log Analytics workspace exists in Terraform, but no Application Insights resource | Check if Container Apps are sending stdout to Log Analytics (likely yes, by default) |
| Celery Flower deployment | Not found in docker-compose or Terraform | Not deployed — queue metrics are blind |
| Database connection pool exhaustion | Pool set to 5+5 in `db/base.py:9-10` | Under load with 4 concurrent workers + API, may hit pool limits. Needs load testing |
| Frontend bundle size / performance budget | No Lighthouse CI, no bundle analyzer configured | Add `@next/bundle-analyzer` for visibility |
| Provider rate limit handling | `tenacity` is in deps but usage patterns vary by provider | Audit all `@retry` decorators for consistent backoff strategy |
| Cost of telemetry overhead | No measurements | Benchmark OTel SDK overhead on provider call hot paths before enabling 100% tracing |
| `min_status` filter consistency | Only `/images` (Unfiled) verified | Audit `/images/all`, `/images/folder/[id]`, search results, cluster detail for PENDING image visibility |
| Storage orphan count | No tooling exists | Implement reconciliation job; count orphans as a metric |
| `folder.image_count` drift | Not measured | Add admin reconciliation endpoint or periodic check |

---

## Appendix: Key File References

### Backend

| File | Relevance |
|---|---|
| `backend/app/main.py` | FastAPI app, logging config, health check, middleware |
| `backend/app/services/billing_context.py` | Thread-local context: trace_id, user_id, job_id, idempotency keys |
| `backend/app/services/log_service.py` | `write_log()` — central structured logging to pipeline_logs table |
| `backend/app/services/billing_orchestrator.py` | Cost decision lifecycle, idempotency, trace_id usage |
| `backend/app/services/billing_service.py` | `finalize_job_billing()`, usage record creation |
| `backend/app/workers/celery_app.py` | Celery config, rate limits, queue routing, worker logging setup |
| `backend/app/workers/tasks.py` | All pipeline tasks (ingest, tag, describe, embed, cluster, etc.) |
| `backend/app/workers/generation_tasks.py` | Training, generation, editing, evaluation tasks |
| `backend/app/models/job.py` | Job model: statuses, types, cost tracking fields |
| `backend/app/models/pipeline_log.py` | PipelineLog model: structured log schema |
| `backend/app/models/billing.py` | UsageRecord, UserBalance, BalanceTransaction models |
| `backend/app/models/cost_decision.py` | CostDecision model: billing lifecycle tracking |
| `backend/app/providers/openai_provider.py` | OpenAI API call logging pattern (AUDIT logs) |
| `backend/app/providers/anthropic_provider.py` | Anthropic API call logging pattern |
| `backend/app/providers/fal_provider.py` | fal.ai provider: request_id tracking, cancellation |
| `backend/app/db/base.py` | SQLAlchemy pool config (pool_size=5, max_overflow=5) |
| `backend/app/core/security.py` | JWT auth, user extraction dependencies |

### Frontend

| File | Relevance |
|---|---|
| `frontend/src/app/layout.tsx` | Root layout, TanStack Query setup, Toaster |
| `frontend/src/lib/api.ts` | Axios client, interceptors, upload chunking, error handling |
| `frontend/src/contexts/AuthContext.tsx` | Session/token management |
| `frontend/src/contexts/UploadContext.tsx` | Upload progress tracking |
| `frontend/src/hooks/useJobNotifications.ts` | Job polling (5s), status change detection |
| `frontend/src/app/admin/MetricsView.tsx` | Admin metrics dashboard (30s polling) |
| `frontend/src/app/admin/OperationsMonitor.tsx` | Admin billing operations monitoring |
| `frontend/package.json` | Dependencies (no observability SDKs) |

### Infrastructure

| File | Relevance |
|---|---|
| `docker-compose.yml` | All local services, health checks, Redis DB allocation |
| `infra/modules/container_apps/main.tf` | Log Analytics workspace, Container App environment |
| `.github/workflows/deploy-dev.yml` | CI/CD health checks, smoke tests |
| `.github/workflows/ci.yml` | PR validation (lint + build) |

---

## I) Privacy Model — Per-User Telemetry Toggle

### Current State: No Privacy Restrictions

**We have no real users yet.** All telemetry captures everything: raw `user_id`, prompts, filenames, search queries, image metadata, full provider request/response payloads. This is intentional and correct for the current development phase — we need full visibility for debugging.

### Future State: Per-User Privacy Flag

When real users are onboarded, privacy will be controlled at the **user level**, not globally. This allows test accounts to remain fully observable while protecting real users.

#### Design

Add a `telemetry_private` boolean column to the `User` model (default: `true` for new registrations, `false` for existing test/admin accounts).

```
User model:
  telemetry_private: bool = True   # New users are private by default
                                    # Test/admin accounts can be set to False
```

#### What the flag controls

| Data Category | `telemetry_private = false` (test accounts) | `telemetry_private = true` (real users) |
|---|---|---|
| `user_id` in logs/traces | Raw integer | Hashed (`sha256(user_id + salt)`) |
| Prompts (generation, search, vision) | Full text captured | Redacted or not captured |
| Image filenames | Full filename | Not captured |
| Search queries | Full query text | Not captured |
| Provider request/response payloads | Full (AUDIT logs) | Stripped to metadata only (tokens, duration, cost) |
| Session replay | Full replay including images | Images masked, prompts redacted |
| Error stack traces | Full detail | Full detail (no PII in stack traces) |
| Job parameters | Full JSON | Sensitive fields stripped |
| Sentry breadcrumbs | Full detail | Sanitized |

#### Implementation approach

1. **Backend middleware** reads `telemetry_private` from the authenticated user (cached in JWT claims or fetched once per request).
2. A **telemetry context** helper (like `billing_context`) stores the flag for the current request/task.
3. **`write_log()`** checks the flag before storing prompts, filenames, or other sensitive data in `extra` JSON.
4. **Sentry `before_send` hook** checks the flag and scrubs PII fields from events for private users.
5. **Provider AUDIT logs** skip full request/response bodies for private users; only emit metadata.
6. **Frontend session replay** (when added) uses the flag to decide masking rules.

#### When to implement

- **Now:** No action needed. All telemetry is full-fidelity.
- **Before public launch:** Add the `telemetry_private` column and the middleware/hooks described above.
- **Admin toggle:** Admins can flip `telemetry_private` per user via the existing user management endpoints (`PATCH /api/auth/users/{id}`).

#### Test account convention

All accounts used for internal testing/development should have `telemetry_private = false`. The seed admin (`stuart.leal23@gmail.com`) and any accounts created during development default to non-private. New user registrations default to `telemetry_private = true`.

> **TODO (pre-launch):** Implement the `telemetry_private` flag on User model, add the Sentry `before_send` scrubber, update `write_log()` to respect the flag, and update provider AUDIT logging. Track this as a separate work item when real user onboarding is planned.
