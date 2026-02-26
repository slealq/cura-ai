# Billing & Costing Forensic Audit

**Generated:** 2026-02-25
**Scope:** Full codebase of cura-ai — every model, every task, every cost path
**Methodology:** Every claim grounded in code with file:line citations

---

## A. Executive Summary

### Key Findings

1. **Estimation vs Actual divergence for fal.ai generation/training/editing:** Estimation uses `cost_per_call` from the catalog (a fixed number set at migration time). Actual cost uses `result.get("cost")` — the provider-reported cost, which varies by image size, steps, and queue load. These will diverge whenever fal.ai changes pricing or the user changes parameters (steps, resolution).

2. **No token estimation for vision cost quotes uses real image dimensions:** The `/billing/vision-costs` POST endpoint accepts `width`/`height` and computes image token counts, but the default GET endpoint falls back to 1024x1024. Folder-based estimation averages dimensions across all folder images, which is good.

3. **Clustering and summarization are "free" in billing:** `cluster_all_images` has no provider calls and no billing. `summarize_cluster` calls an LLM but billing IS recorded via `write_log`. However, there is no pre-estimation endpoint for summarization costs.

4. **`evaluate_lora` has no job-level cost recording:** Unlike `train_lora`/`generate_image`/`edit_image`, the evaluation task does not call `_record_job_cost()`. Individual provider calls are billed, but `job.charged_cost` is never set, so the Jobs page shows "-" for evaluation jobs.

5. **PipelineLog has no `provider_cost` column:** The fal.ai cost flows through `write_log(provider_cost=...)` to `record_usage_standalone()` but is NOT persisted on the `pipeline_logs` table itself. It's only stored in `usage_records.raw_cost` and `usage_records.detail` JSON.

6. **No automated billing tests exist.** Zero test files reference billing, cost, or sparks.

7. **`cost_sparks` on GeneratedImage is computed at read time**, not stored. It divides `job.charged_cost` by `job.total_items` — correct for batch but potentially misleading if some items in a batch fail.

8. **Expand prompt billing bypasses `write_log`:** The `expand_prompt` endpoint calls `BillingService.record_usage()` directly (not through the provider/write_log path), so no `PipelineLog` entry is created, and `pipeline_log_id` on the `UsageRecord` is NULL.

---

## B. System-Wide Architecture

### Cost Ledger Schema

```
┌──────────────┐     ┌──────────────────┐     ┌───────────────────┐
│ CostCatalog  │     │  UsageRecord     │     │ BalanceTransaction│
│              │     │                  │     │                   │
│ provider     │◄────│ provider         │     │ user_id           │
│ model        │     │ model            │     │ amount (sparks)   │
│ operation    │     │ operation        │     │ transaction_type  │
│ cost_per_*   │     │ input_tokens     │     │ description       │
│ platform_    │     │ output_tokens    │     │ reference_id ─────┼──► usage_records.id
│   markup     │     │ raw_cost (USD)   │     │ created_by        │
│              │     │ charged_cost(USD)│     │ created_at        │
│              │     │ detail (JSON)    │     └───────────────────┘
│              │     │ pipeline_log_id──┼──► pipeline_logs.id
└──────────────┘     └──────────────────┘
                            │
                            ▼
┌──────────────┐     ┌──────────────────┐
│ UserBalance  │     │  Job             │
│              │     │                  │
│ user_id (UQ) │     │ charged_cost     │
│ balance      │     │   (sparks)       │
│  (sparks)    │     │ total_items      │
│ currency     │     │                  │
└──────────────┘     └──────────────────┘
```

**Currency:** 1 spark = $0.001 USD. Constant `USD_TO_SPARKS = Decimal("1000")` at `billing_service.py:21`.

### Where Estimates Happen

| Endpoint | File | What It Estimates |
|----------|------|-------------------|
| `GET /billing/generation-costs` | `billing.py:194-218` | Per-image generation cost by base model |
| `GET /billing/edit-costs` | `billing.py:231-237` | Per-call edit cost by edit model |
| `GET /billing/training-costs` | `billing.py:240-246` | Per-job training cost by base model |
| `GET /billing/vision-costs` | `billing.py:364-374` | Per-image vision cost (default 1024x1024) |
| `POST /billing/vision-costs` | `billing.py:377-403` | Per-image vision cost (specific dimensions) |
| `_compute_vision_costs()` | `billing.py:276-361` | Shared vision cost computation |

### Where Actual Costs Are Computed

Two paths depending on provider:

**Path A — Token-based (OpenAI, Anthropic, fal-vision/OpenRouter):**
```
Provider API response → usage.prompt_tokens, usage.completion_tokens
  → write_log() → record_usage_standalone()
  → _calculate_cost() looks up CostCatalog
  → raw_cost = (input_tokens × cost_per_input) + (output_tokens × cost_per_output) + cost_per_call
  → charged_cost = raw_cost × platform_markup
```
Code ref: `billing_service.py:230-283`

**Path B — Provider-reported (fal.ai generation/training/editing):**
```
Provider API response → result.get("cost")
  → write_log(provider_cost=fal_cost) → record_usage_standalone()
  → _calculate_cost() uses provider_cost directly
  → raw_cost = provider_cost
  → charged_cost = raw_cost × platform_markup
```
Code ref: `billing_service.py:204-228`

### Where Charges Are Computed & Persisted

1. **Immediate debit** (default): `BillingService.record_usage()` calls `debit_usage()` after creating `UsageRecord` — `billing_service.py:177-183`
2. **Deferred debit** (pipeline): `finalize_pipeline_billing()` aggregates all deferred `UsageRecord`s for a job, creates ONE `BalanceTransaction` — `billing_service.py:686-748`
3. **Job cost copy**: `_record_job_cost()` copies the latest `UsageRecord.charged_cost × 1000` to `Job.charged_cost` — `generation_tasks.py:39-60`

---

## C. Cost Catalog — Per-Model Analysis

### C.1 OpenAI GPT-4o

**Identification:**
- Provider: `openai`
- Model ID: configurable via `settings.openai_vision_model` (factory: `providers/__init__.py:130`)
- Catalog model: `gpt-4o`
- Endpoint: `client.chat.completions.create()` — `openai_provider.py:104`
- Modes: vision (tag, describe), evaluation, cluster summarization

**Parameters Affecting Cost:**
- Input tokens: image tokens (resolution-dependent) + prompt tokens
- Output tokens: response length (constrained by `max_tokens`)
- Image token formula: tile-based — `token_estimator.py:37-50`
  ```
  scaled_w, scaled_h = _scale_image(width, height, 2048, 768)
  tiles_w = ceil(scaled_w / 512)
  tiles_h = ceil(scaled_h / 512)
  tokens = tiles_w × tiles_h × 170 + 85
  ```

**Catalog Pricing (from migration 029):**
- `cost_per_input_token`: $0.0000025 ($2.50/1M)
- `cost_per_output_token`: $0.00001 ($10.00/1M)
- `cost_per_call`: $0
- `platform_markup`: 2.0x
- Operations: tag, describe, evaluate, evaluate_creative, summarize, summarize_eval, generate_prompts

**ESTIMATION formula (`_compute_vision_costs` at `billing.py:276-361`):**
```
input_tokens = DB_average(provider, model, operation) OR estimate_vision_input_tokens(provider, model, W, H, prompt)
output_tokens = DB_average(provider, model, operation) OR DEFAULT_OUTPUT_TOKENS[mode]
  DEFAULT_OUTPUT_TOKENS = {tag: 500, describe: 700, custom: 600}  # token_estimator.py:8-12

raw = input_tokens × $0.0000025 + output_tokens × $0.00001
charged = raw × 2.0
sparks = charged × 1000
```

**ACTUAL COST (`_calculate_cost` at `billing_service.py:230-283`):**
```
input_tokens = response.usage.prompt_tokens      # from OpenAI API
output_tokens = response.usage.completion_tokens  # from OpenAI API

raw = input_tokens × cost_per_input_token + output_tokens × cost_per_output_token + cost_per_call
charged = raw × platform_markup
```
Tokens extracted at `openai_provider.py:141-153` and passed through `write_log()`.

**BILLING/PRICE:**
```
sparks = charged_cost × 1000
```
Debited immediately unless inside `process_image_pipeline` (deferred).

**Telemetry Captured:**
- `PipelineLog`: provider, model, operation, input_tokens, output_tokens, duration_ms — `log_service.py:44-62`
- `UsageRecord`: raw_cost, charged_cost, detail (JSON with rates), input_tokens, output_tokens — `billing_service.py:162-173`

**Gaps:** No `provider_cost` on PipelineLog. Token counts are actual (good).

**Validation Status:** NO AUTOMATED TESTS.

**Known Mismatches:** None identified — catalog rates match OpenAI's published GPT-4o pricing at time of writing.

---

### C.2 OpenAI GPT-5.2

**Identification:**
- Provider: `openai`
- Catalog model: `gpt-5.2`
- Added by migration 032
- Uses `max_completion_tokens` param and 2x reasoning buffer — `openai_provider.py:39-53`

**Parameters Affecting Cost:**
- Same as GPT-4o but different image token formula for gpt-5 family:
  ```python
  # token_estimator.py:40-43
  scaled_w, scaled_h = _scale_image(width, height, 2048, 768)
  pixels = scaled_w * scaled_h
  return max(800, pixels // 500)
  ```
- Reasoning models get 2x `max_completion_tokens` buffer — `openai_provider.py:44-53`

**Catalog Pricing (migration 032):**
- `cost_per_input_token`: $0.00000175 ($1.75/1M)
- `cost_per_output_token`: $0.000014 ($14.00/1M)
- `cost_per_call`: $0
- `platform_markup`: 2.0x
- Operations: tag, describe, evaluate, evaluate_creative, summarize, summarize_eval, generate_prompts

**ESTIMATION / ACTUAL / BILLING:** Same formulas as GPT-4o, different rates.

**Known Mismatches:** Reasoning tokens (invisible to user but billed by OpenAI) may not appear in `response.usage.completion_tokens` depending on API version. The 2x buffer in `max_completion_tokens` suggests awareness but cost recording uses whatever OpenAI reports.

---

### C.3 OpenAI GPT-4o-mini

**Identification:**
- Provider: `openai`
- Catalog model: `gpt-4o-mini`
- Used for: `expand_prompt` (migration 031), + all 7 LLM ops (migration 034)

**Catalog Pricing:**
- `cost_per_input_token`: $0.00000015 ($0.15/1M)
- `cost_per_output_token`: $0.0000006 ($0.60/1M)
- `platform_markup`: 2.0x
- Operations: expand_prompt, tag, describe, evaluate, evaluate_creative, summarize, summarize_eval, generate_prompts

**Expand Prompt Specifics:**
- Endpoint: `generation.py:356-426`
- Billing: Direct `BillingService.record_usage()` call, NOT via `write_log` — `generation.py:410-418`
- Balance check: `generation.py:369`
- No `PipelineLog` created (billing bypasses log service)

**Expand Prompt ESTIMATION (`billing.py:194-218`):**
```
input_tokens = estimate_prompt_tokens("Expand this prompt...") ≈ len(system_prompt) // 4
output_tokens = DB_average("openai", model, "expand_prompt") OR 200 (hardcoded default)
raw = input_cost + output_cost
charged = raw × platform_markup
expand_cost_sparks = charged × 1000
```

---

### C.4 OpenAI GPT-5-mini

**Identification:**
- Provider: `openai`
- Catalog model: `gpt-5-mini`
- Added by migrations 032 (expand_prompt) and 034 (all 7 LLM ops)

**Catalog Pricing:**
- `cost_per_input_token`: $0.00000025 ($0.25/1M)
- `cost_per_output_token`: $0.000002 ($2.00/1M)
- `platform_markup`: 2.0x

---

### C.5 OpenAI text-embedding-3-small

**Identification:**
- Provider: `openai`
- Model: `text-embedding-3-small` (hardcoded at `openai_provider.py:318`)
- Endpoint: `client.embeddings.create()` — `openai_provider.py:326-329`
- Dimensions: 1536 — `openai_provider.py:389`

**Parameters Affecting Cost:**
- Input tokens only (embeddings have no output tokens)
- Token count: `response.usage.total_tokens` — `openai_provider.py:344`

**Catalog Pricing (migration 029):**
- `cost_per_input_token`: $0.00000002 ($0.02/1M)
- `cost_per_output_token`: $0
- `cost_per_call`: $0
- `platform_markup`: 2.0x

**ESTIMATION (`token_estimator.py:93-109` + `billing.py:306-313`):**
```
embed_tokens = estimate_embed_tokens(tags, description)
  If both None: return 350
  Else: combined = ", ".join(tags) + " " + description
        return max(1, len(combined) // 4)

raw = embed_tokens × $0.00000002
charged = raw × 2.0
sparks = charged × 1000
```

**ACTUAL COST:**
```
input_tokens = response.usage.total_tokens  # from OpenAI API
output_tokens = 0  # embeddings have none
```
Extracted at `openai_provider.py:344-351`.

**Telemetry Captured:** `input_tokens=usage.total_tokens` logged; no output_tokens for embeddings. Token is actual from API.

---

### C.6 Anthropic Claude Sonnet 4.6

**Identification:**
- Provider: `anthropic`
- Catalog model: `claude-sonnet-4-6` (migration 035; replaces `claude-sonnet-4-20250514` dropped in migration 036)
- Endpoint: `client.messages.create()` — `anthropic_provider.py:90-110`
- Temperature clamped to max 1.0 — `anthropic_provider.py:70`

**Parameters Affecting Cost:**
- Input tokens: image tokens + prompt tokens
- Image token formula: `max(1, (width × height) // 750)` — `token_estimator.py:53-55`
- Output tokens: response length

**Catalog Pricing (migration 035):**
- `cost_per_input_token`: $0.000003 ($3.00/1M)
- `cost_per_output_token`: $0.000015 ($15.00/1M)
- `platform_markup`: 2.0x
- Operations: tag, describe, evaluate, evaluate_creative, summarize, summarize_eval, generate_prompts

**ACTUAL COST:**
```
input_tokens = response.usage.input_tokens    # from Anthropic API
output_tokens = response.usage.output_tokens  # from Anthropic API
```
Extracted at `anthropic_provider.py:113-125`.

**ESTIMATION / BILLING:** Same pattern as OpenAI models — catalog lookup + markup.

---

### C.7 Anthropic Claude Opus 4.6

**Catalog Pricing (migration 035):**
- `cost_per_input_token`: $0.000005 ($5.00/1M)
- `cost_per_output_token`: $0.000025 ($25.00/1M)
- `platform_markup`: 2.0x
- Operations: tag, describe, evaluate, evaluate_creative, summarize, summarize_eval, generate_prompts

---

### C.8 Anthropic Claude Haiku 4.5

**Catalog Pricing (migration 035):**
- `cost_per_input_token`: $0.000001 ($1.00/1M)
- `cost_per_output_token`: $0.000005 ($5.00/1M)
- `platform_markup`: 2.0x

---

### C.9 Anthropic Claude 3 Haiku

**Catalog Pricing (migration 035):**
- `cost_per_input_token`: $0.00000025 ($0.25/1M)
- `cost_per_output_token`: $0.00000125 ($1.25/1M)
- `platform_markup`: 2.0x

---

### C.10 fal.ai Grok-4-fast (via OpenRouter)

**Identification:**
- Provider: `fal` (catalog) / goes through fal.ai → OpenRouter
- Model: `x-ai/grok-4-fast` — `fal_vision_provider.py:29`
- Endpoint: `fal-ai/openrouter/router/vision` — `fal_vision_provider.py:28`
- Used for: tagging, describing, evaluation when provider=fal

**Parameters Affecting Cost:**
- Input tokens: image + prompt (via OpenRouter's token counting)
- Output tokens: response length
- **Also returns `cost` directly in usage dict** — `fal_vision_provider.py:113`

**Catalog Pricing (migration 029):**
- `cost_per_input_token`: $0.0000002 ($0.20/1M)
- `cost_per_output_token`: $0.0000005 ($0.50/1M)
- `cost_per_call`: $0
- `platform_markup`: 2.0x
- Operations: tag, describe, evaluate, evaluate_creative, summarize_eval, generate_prompts

**ACTUAL COST — DUAL PATH:**
The fal vision provider passes BOTH `provider_cost` AND tokens to `write_log`:
```python
# fal_vision_provider.py:106-119
usage = result.get("usage", {})
write_log(
    input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
    output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
    provider_cost=usage.get("cost"),  # OpenRouter returns cost directly
    ...
)
```
When `provider_cost` is not None, `_calculate_cost()` uses Path B (provider-reported). If OpenRouter doesn't return cost, it falls back to Path A (catalog token-based).

**Known Mismatches:** OpenRouter pricing may differ from catalog rates. When `provider_cost` is returned, catalog token rates are ignored — only `platform_markup` is used.

---

### C.11 Qwen3-VL-235B (via fal/OpenRouter)

**Identification:**
- Provider: `fal`
- Catalog model: `qwen/qwen3-vl-235b-a22b-instruct`
- Added by migration 037

**Catalog Pricing:**
- `cost_per_input_token`: $0.0000002 ($0.20/1M)
- `cost_per_output_token`: $0.00000088 ($0.88/1M)
- `platform_markup`: 2.0x
- Operations: tag, describe, evaluate, evaluate_creative, summarize_eval, generate_prompts

**Same billing flow as Grok-4-fast** — dual path (provider_cost if available, else catalog).

---

### C.12 Gemini 2.5 Flash (via fal/OpenRouter)

**Identification:**
- Provider: `fal`
- Catalog model: `google/gemini-2.5-flash`
- Added by migration 038

**Catalog Pricing:**
- `cost_per_input_token`: $0.0000003 ($0.30/1M)
- `cost_per_output_token`: $0.0000025 ($2.50/1M)
- `platform_markup`: 2.0x
- Operations: tag, describe, evaluate, evaluate_creative, summarize_eval, generate_prompts

---

### C.13 fal.ai flux-dev (Generation)

**Identification:**
- Provider: `fal`
- Training endpoint: `fal-ai/flux-lora-fast-training` — `fal_provider.py:27`
- Generation with LoRA: `fal-ai/flux-lora` — `fal_provider.py:28`
- Generation without LoRA: `fal-ai/flux/dev` — `fal_provider.py:29`

**Parameters Affecting Cost:**
- Resolution (width × height)
- Number of inference steps (default 28)
- Number of LoRAs (up to 2)
- fal.ai determines cost — NOT token-based

**Catalog Pricing (migration 029):**

| Endpoint | Operation | cost_per_call | platform_markup |
|----------|-----------|---------------|-----------------|
| `fal-ai/flux-lora` | generate | $0.035 | 2.0x |
| `fal-ai/flux/dev` | generate | $0.025 | 2.0x |
| `fal-ai/flux-lora-fast-training` | train | $2.00 | 2.0x |

**ESTIMATION (`billing_service.py:389-420`):**
```python
GENERATION_MODEL_MAP = {
    "flux-dev": {
        "without_lora": ("fal", "fal-ai/flux/dev", "generate"),
        "with_lora": ("fal", "fal-ai/flux-lora", "generate"),
    },
    ...
}
```
```
sparks_estimate = cost_per_call × platform_markup × 1000
  flux-dev without_lora = $0.025 × 2.0 × 1000 = 50 sparks
  flux-dev with_lora    = $0.035 × 2.0 × 1000 = 70 sparks
```

**ACTUAL COST (`fal_provider.py:316` + `billing_service.py:204-228`):**
```
fal_cost = result.get("cost")  # Provider-reported USD
raw_cost = Decimal(str(fal_cost))
charged_cost = raw_cost × platform_markup  # 2.0x
sparks = charged_cost × 1000
```

**BILLING/PRICE:**
- Immediate debit via `record_usage_standalone()` (not deferred)
- `_record_job_cost()` copies to `Job.charged_cost` — `generation_tasks.py:620`

**Telemetry Captured:**
- `PipelineLog`: provider="fal", model=endpoint, operation="generate", duration_ms (no tokens, no provider_cost column)
- `UsageRecord`: raw_cost, charged_cost, detail=`{cost_source: "provider", provider_cost: X, platform_markup: 2.0, sparks: Y}`

**Known Mismatches:**
- **ESTIMATION uses `cost_per_call` (fixed)** but **ACTUAL uses `result.get("cost")` (variable)**. fal.ai pricing depends on resolution, steps, and queue load. The catalog `cost_per_call` is a static approximation that WILL diverge from actual.

---

### C.14 fal.ai qwen-2.5 (Generation)

**Identification:**
- Provider: `fal`
- Training: `fal-ai/qwen-image-2512-trainer-v2` — `fal_provider.py:35`
- Generation with LoRA: `fal-ai/qwen-image-2512/lora` — `fal_provider.py:36`
- Generation without LoRA: `fal-ai/qwen-image-2512` — `fal_provider.py:37`

**Catalog Pricing (migration 029):**

| Endpoint | Operation | cost_per_call | platform_markup |
|----------|-----------|---------------|-----------------|
| `fal-ai/qwen-image-2512/lora` | generate | $0.035 | 2.0x |
| `fal-ai/qwen-image-2512` | generate | $0.02 | 2.0x |
| `fal-ai/qwen-image-2512-trainer-v2` | train | $1.90 | 2.0x |

**ESTIMATION:**
```
qwen-2.5 without_lora = $0.02 × 2.0 × 1000 = 40 sparks
qwen-2.5 with_lora    = $0.035 × 2.0 × 1000 = 70 sparks
```

**Same actual cost flow as flux-dev** — provider-reported cost.

---

### C.15 fal.ai nano-banana-pro (Generation)

**Identification:**
- Provider: `fal`
- Generation only (no LoRA, no training): `fal-ai/nano-banana-pro` — `fal_provider.py:43`
- Uses `resolution_aspect` instead of `width`/`height` — `fal_provider.py:44`

**Catalog Pricing (migration 029, fixed in migration 030):**
- `cost_per_call`: $0.039 (was $0.15 before fix)
- `platform_markup`: 2.0x

**ESTIMATION:**
```
nano-banana-pro = $0.039 × 2.0 × 1000 = 78 sparks
```
Note: `GENERATION_MODEL_MAP` only has `"without_lora"` variant for nano-banana-pro — `billing_service.py:398-400`.

---

### C.16 fal.ai Edit Models (6 models)

**Identification (all provider: `fal`):**

| Edit Model Key | fal.ai Endpoint | cost_per_call |
|---|---|---|
| `qwen-image-max-edit` | `fal-ai/qwen-image-max-edit` | $0.075 |
| `kling-image` | `fal-ai/kling-image/v2/image-to-image` | $0.028 |
| `wan-25` | `fal-ai/wan-2.5/v1/image-to-image` | $0.05 |
| `grok-imagine` | `fal-ai/grok-2-image/image-to-image` | $0.022 |
| `face-swap` | `fal-ai/face-swap` | $0.009 |
| `nano-banana-pro-edit` | `fal-ai/nano-banana-pro/edit` | $0.039 |

All have `platform_markup`: 2.0x. Endpoints from `fal_provider.py:384-441`.

**EDIT_MODEL_MAP (`billing_service.py:423-430`):**
```python
EDIT_MODEL_MAP = {
    "qwen-image-max-edit": ("fal", "fal-ai/qwen-image-max-edit", "edit"),
    "kling-image": ("fal", "fal-ai/kling-image/v2/image-to-image", "edit"),
    "wan-25": ("fal", "fal-ai/wan-2.5/v1/image-to-image", "edit"),
    "grok-imagine": ("fal", "fal-ai/grok-2-image/image-to-image", "edit"),
    "face-swap": ("fal", "fal-ai/face-swap", "edit"),
    "nano-banana-pro-edit": ("fal", "fal-ai/nano-banana-pro/edit", "edit"),
}
```

**ESTIMATION (`billing_service.py:438-450`):**
```
sparks_estimate = cost_per_call × platform_markup × 1000
```

| Edit Model | Estimated Sparks |
|---|---|
| qwen-image-max-edit | 150 |
| kling-image | 56 |
| wan-25 | 100 |
| grok-imagine | 44 |
| face-swap | 18 |
| nano-banana-pro-edit | 78 |

**ACTUAL COST:**
```
fal_cost = result.get("cost")  # fal_provider.py:540
```
Same provider-reported flow as generation.

---

### C.17 fal.ai Training Models

**Identification:**

| Base Model | Training Endpoint | cost_per_call |
|---|---|---|
| `flux-dev` | `fal-ai/flux-lora-fast-training` | $2.00 |
| `qwen-2.5` | `fal-ai/qwen-image-2512-trainer-v2` | $1.90 |

**TRAINING_MODEL_MAP (`billing_service.py:433-436`):**
```python
TRAINING_MODEL_MAP = {
    "flux-dev": ("fal", "fal-ai/flux-lora-fast-training", "train"),
    "qwen-2.5": ("fal", "fal-ai/qwen-image-2512-trainer-v2", "train"),
}
```

**ESTIMATION (`billing_service.py:452-464`):**
```
flux-dev training  = $2.00 × 2.0 × 1000 = 4000 sparks
qwen-2.5 training  = $1.90 × 2.0 × 1000 = 3800 sparks
```

**ACTUAL COST:**
```
fal_cost = result.get("cost")  # fal_provider.py:171
```

**Known Mismatch:** Training cost varies significantly by number of images, steps, and model. The $2.00/$1.90 catalog values are rough averages. Actual costs from fal.ai will vary.

---

## D. Task Cost Trees

### D.1 Tag Single Image

```
tag_image (tasks.py:447-532)
└── get_tagger() → tagger.tag_image()
    └── [BILLABLE] write_log(provider, model, operation="tag", input_tokens, output_tokens)
        └── record_usage_standalone() → UsageRecord + BalanceTransaction (immediate debit)
```

**Aggregation:** Single operation, single debit.
**Ledger:** `UsageRecord` with `pipeline_log_id` linking to `PipelineLog`.
**Customer sees:** Balance reduced immediately. Cost visible in Billing page usage summary and Image Drawer processing costs.

---

### D.2 Describe Single Image

```
describe_image (tasks.py:535-617)
└── get_describer() → describer.describe_image()
    └── [BILLABLE] write_log(provider, model, operation="describe", input_tokens, output_tokens)
        └── record_usage_standalone() → UsageRecord + BalanceTransaction (immediate debit)
```

Same pattern as tag. Auto-chains to `embed_image` if tags exist.

---

### D.3 Embed Single Image

```
embed_image (tasks.py:622-695)
└── get_embedder() → embedder.embed_text()
    └── [BILLABLE] write_log(provider="openai", model="text-embedding-3-small", operation="embed", input_tokens)
        └── record_usage_standalone() → UsageRecord + BalanceTransaction (immediate debit)
```

---

### D.4 Process Image Pipeline (Tag + Describe + Embed)

```
process_image_pipeline (tasks.py:1002-1131)
│   set_billing_deferred(True)  ← line 1020
│
├── get_tagger() → tagger.tag_image()
│   └── [BILLABLE] write_log(operation="tag") → UsageRecord (deferred, NO debit)
│
├── get_describer() → describer.describe_image()
│   └── [BILLABLE] write_log(operation="describe") → UsageRecord (deferred, NO debit)
│
├── get_embedder() → embedder.embed_text()
│   └── [BILLABLE] write_log(operation="embed") → UsageRecord (deferred, NO debit)
│
└── finally:
    └── finalize_pipeline_billing(db, user_id, job_id)  ← line 1126
        ├── SUM all UsageRecord.charged_cost for this job
        ├── Create ONE BalanceTransaction (debit)
        └── Set Job.charged_cost = total_sparks
```

**Aggregation:** 3 operations → 3 `UsageRecord`s → 1 `BalanceTransaction`.
**Description format:** `"Describe image.jpg (tag: 1.5 + describe: 4.2 + embed: 0.02 sparks)"`
**Customer sees:** Single debit in transaction history. Total cost on Job row.

---

### D.5 Full Pipeline (All Images)

```
run_full_pipeline (tasks.py:1135-1230)
│
├── FOR EACH image:
│   └── process_image_pipeline.delay(image_id, user_id, job_id)
│       └── [See D.4 above - each image gets its own cost tree]
│
├── cluster_all_images.delay()  ← FREE (no provider calls)
│
└── summarize_clusters.delay()
    └── FOR EACH cluster:
        └── summarize_cluster(cluster_id, user_id)
            └── get_cluster_summarizer() → provider.summarize_cluster()
                └── [BILLABLE] write_log(operation="summarize") → UsageRecord + BalanceTransaction (immediate)
```

**Aggregation:** N images × (tag+describe+embed) + M clusters × summarize.
**Customer sees:** N pipeline debits + M summarize debits in transaction history.

---

### D.6 Describe All (Batch from Dialog)

```
User clicks "Describe All" in DescribeAllDialog
│
├── [PRE-ESTIMATION shown in UI]
│   POST /billing/vision-costs {folder_id: X}
│   └── _compute_vision_costs(db, user_id, avg_width, avg_height)
│       └── Returns per-model costs (tag, describe, embed, total per image)
│
└── Backend dispatches batch job → FOR EACH image:
    └── process_image_pipeline.delay()
        └── [See D.4 above]
```

**Customer sees:** Cost estimate before confirming: `~{costPerImage × imageCount} sparks ({costPerImage}/image)` — `DescribeAllDialog.tsx:417-423`.

---

### D.7 Generate Image

```
generate_image (generation_tasks.py:531-682)
│   set_billing_user(user_id)  ← line 544
│
├── get_generator() → generator.generate()
│   └── [BILLABLE] write_log(operation="generate", provider_cost=fal_cost)
│       └── record_usage_standalone() → UsageRecord + BalanceTransaction (immediate debit)
│
└── _record_job_cost(db, job_id, user_id, "generate")  ← line 620
    └── Copies UsageRecord.charged_cost × 1000 → Job.charged_cost
```

**Customer sees:**
- Pre-estimate: `GET /billing/generation-costs` → sparks per image — `Generate page`
- Post-run: `Job.charged_cost` shown in Jobs page; `cost_sparks` computed per-image at read time — `generation.py:319-324`

---

### D.8 Batch Generate

```
batch_generate (generation_tasks.py:700-813)
│
└── FOR EACH image in batch:
    └── generate_image.delay(generated_image_id, user_id, job_id)
        └── [See D.7 above]
```

**Note:** Each individual generate_image task calls `_record_job_cost()`, which overwrites `Job.charged_cost` with the LAST image's cost. This is a **BUG** — batch jobs should sum costs, not overwrite.

**WAIT — re-examining:** `_record_job_cost` at `generation_tasks.py:39-60` queries the most recent `UsageRecord` for the operation and copies its cost. For batch jobs with a shared `job_id`, each image's `_record_job_cost` overwrites the previous. The `cost_sparks` per image is then computed as `job.charged_cost / job.total_items` — `generation.py:323-324`. This means only the LAST image's cost is used as the denominator-divided value, which is incorrect if costs vary per image.

---

### D.9 Train LoRA

```
train_lora (generation_tasks.py:220-528)
│
├── get_trainer() → trainer.start_training()
│   └── No cost yet (returns request_id)
│
├── POLL for completion (5-15s intervals)
│
├── trainer.get_training_result(request_id)
│   └── [BILLABLE] write_log(operation="train", provider_cost=fal_cost)
│       └── record_usage_standalone() → UsageRecord + BalanceTransaction (immediate)
│
└── _record_job_cost(db, job_id, user_id, "train")  ← line 479
```

**Customer sees:** Pre-estimate: `GET /billing/training-costs` → sparks per job. Post-run: `Job.charged_cost` in Jobs page.

---

### D.10 Edit Image

```
edit_image (generation_tasks.py:863-1011)
│   set_billing_user(user_id)  ← line 874
│
├── get_editor() → editor.edit()
│   └── [BILLABLE] write_log(operation="edit", provider_cost=fal_cost)
│       └── record_usage_standalone() → UsageRecord + BalanceTransaction (immediate)
│
└── _record_job_cost(db, job_id, user_id, "edit")  ← line 951
```

**Customer sees:** Pre-estimate: `GET /billing/edit-costs` → sparks per call. Post-run: `Job.charged_cost` in Jobs page.

---

### D.11 Evaluate LoRA

```
evaluate_lora (generation_tasks.py:1152-1648)
│   set_billing_user(user_id)  ← line 1173
│
├── FOR EACH reference pair (sample_count images):
│   ├── get_generator() → generate()
│   │   └── [BILLABLE] write_log(operation="generate", provider_cost)
│   │
│   ├── get_describer() → describe_image() [for embedding similarity]
│   │   └── [BILLABLE] write_log(operation="describe", input_tokens, output_tokens)
│   │
│   ├── get_embedder() → embed_text() [for embedding similarity]
│   │   └── [BILLABLE] write_log(operation="embed", input_tokens)
│   │
│   └── get_evaluator() → evaluate_pair()
│       └── [BILLABLE] write_log(operation="evaluate", input_tokens, output_tokens)
│
├── FOR EACH creative pair (creative_count prompts):
│   ├── get_generator() → generate()
│   │   └── [BILLABLE] write_log(operation="generate", provider_cost)
│   │
│   └── get_evaluator() → evaluate_single()
│       └── [BILLABLE] write_log(operation="evaluate_creative", input_tokens, output_tokens)
│
├── get_evaluator() → generate_creative_prompts()
│   └── [BILLABLE] write_log(operation="generate_prompts", input_tokens, output_tokens)
│
└── get_evaluator() → summarize_assessments()
    └── [BILLABLE] write_log(operation="summarize_eval", input_tokens, output_tokens)
```

**Aggregation:** Per evaluation with N reference + M creative:
- N × (generate + describe + embed + evaluate) + M × (generate + evaluate_creative) + generate_prompts + summarize_eval

**CRITICAL GAP:** No `_record_job_cost()` call. `Job.charged_cost` is never set for evaluation jobs.

**No pre-estimation endpoint exists** for evaluation costs.

---

### D.12 Expand Prompt

```
expand_prompt (generation.py:356-426)
│
├── BillingService.check_balance_or_raise()  ← line 369
│
├── OpenAI client.chat.completions.create()  ← line 387
│
└── BillingService.record_usage(operation="expand_prompt")  ← line 412-418
    └── UsageRecord + BalanceTransaction (immediate)
    NOTE: No write_log() call, no PipelineLog entry
```

**Customer sees:** Pre-estimate: `GET /billing/generation-costs` → `expand_prompt_cost` field. Post-run: immediate debit.

---

### D.13 Vision Analysis (Standalone)

```
POST /vision/analyze (vision.py:164-240)
│
├── get_tagger() / get_describer()  [includes balance check]
│   └── Tagger/Describer calls write_log()
│       └── [BILLABLE] record_usage_standalone() → UsageRecord + BalanceTransaction (immediate)
│
└── vision_service.create_result()  [saves analysis result, no billing]
```

**Customer sees:** Pre-estimate: `GET /billing/vision-costs` or `POST /billing/vision-costs`. Post-run: immediate debit.

---

### D.14 Cluster Summarization

```
summarize_cluster (tasks.py:882-954)
│
└── get_cluster_summarizer() → summarizer.summarize_cluster()
    └── [BILLABLE] write_log(operation="summarize", input_tokens, output_tokens)
        └── record_usage_standalone() → UsageRecord + BalanceTransaction (immediate)
```

**No pre-estimation endpoint** for summarization costs.

---

## E. Gaps / Unknowns / Required Fixes

### Priority 1 — Data Integrity Issues

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 1 | **`evaluate_lora` does not call `_record_job_cost()`** | `Job.charged_cost` is NULL for evaluation jobs. Jobs page shows "-" for cost. | Add `_record_job_cost(db, job_id, user_id, "evaluate")` at end of evaluate_lora. But evaluation has many operations — need to sum all UsageRecords for the job, not just the last one. Use `finalize_pipeline_billing()` pattern instead. |
| 2 | **`_record_job_cost()` overwrites `Job.charged_cost` with last UsageRecord** | For batch generate/edit, only the last image's cost is recorded on the Job. `cost_sparks = job.charged_cost / total_items` produces wrong per-image cost. | Rewrite `_record_job_cost()` to SUM all UsageRecords for the job, or use deferred billing with `finalize_pipeline_billing()`. |
| 3 | **`expand_prompt` bypasses `write_log()`** | No `PipelineLog` entry created. `pipeline_log_id` on UsageRecord is NULL. Breaks the PipelineLog → UsageRecord join used by `finalize_pipeline_billing()` and `get_processing_costs()`. | Route through `write_log()` or accept the NULL linkage as intentional for non-pipeline operations. |

### Priority 2 — Estimation vs Actual Divergence

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 4 | **Generation/edit/training estimation uses static `cost_per_call`; actual uses provider-reported cost** | Estimates diverge from actual whenever fal.ai pricing changes, or when user selects non-default resolution/steps. | Log actual vs estimated cost per job. Add resolution/steps-aware estimation (e.g., fal.ai publishes per-step pricing). |
| 5 | **No pre-estimation for evaluation costs** | Users cannot see evaluation cost before starting. An evaluation with 10 reference + 5 creative pairs could cost 10×(generate+describe+embed+evaluate) + 5×(generate+evaluate) ≈ significant. | Add `GET /billing/evaluation-costs` endpoint that estimates based on pair counts. |
| 6 | **No pre-estimation for cluster summarization costs** | Users don't see how much summarization will cost before triggering it. | Add cost info to the summarize confirmation UI. |

### Priority 3 — Missing Telemetry

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 7 | **`PipelineLog` has no `provider_cost` column** | Cannot audit provider costs from logs alone — must join to `UsageRecord`. | Add `provider_cost Numeric(12,6) nullable` to PipelineLog. |
| 8 | **fal.ai generation/edit/training don't log token counts** | Token columns are NULL for all fal.ai generation operations. Only `provider_cost` is captured. | fal.ai doesn't return tokens for image operations — this is expected. Document as "N/A for image generation". |
| 9 | **`UsageRecord.pipeline_log_id` has no FK constraint** | Can become a dangling reference if PipelineLog is deleted. | Add FK with `SET NULL` on delete. |

### Priority 4 — Billing Correctness

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 10 | **Catalog wildcard matching order** | `_get_catalog_entry()` tries exact → `*` → partial wildcard (`LIKE %*%`). If model `gpt-4o-2024-05-13` is used but catalog has `gpt-4o`, no match occurs. Only `gpt-4o*` wildcard would match via partial. | Ensure catalog entries use wildcard patterns for versioned models, or add exact entries for each model version. |
| 11 | **Default 2.0x markup when no catalog entry** | If a provider/model/operation combo has no catalog entry, provider-reported cost gets 2.0x markup silently. | Log a WARNING when falling back to default markup. Consider blocking unbilled operations. |
| 12 | **`record_usage_standalone()` swallows exceptions** | If billing fails (DB error, etc.), the provider call succeeds but cost is never recorded. User gets free usage. | At minimum, log at ERROR level and emit a metric. Consider retrying. |

### Priority 5 — Testing & Validation

| # | Issue | Impact | Fix |
|---|-------|--------|-----|
| 13 | **Zero automated billing tests** | No regression safety for cost calculations, catalog lookups, deferred billing, or finalization. | See Validation Plan below. |

### Validation Plan

**Unit Tests (billing_service.py):**
- [ ] `test_calculate_cost_catalog_based` — Given known catalog entry + token counts, assert raw_cost, charged_cost, detail
- [ ] `test_calculate_cost_provider_reported` — Given provider_cost + catalog markup, assert charged_cost
- [ ] `test_calculate_cost_no_catalog_entry` — Assert default 2.0x markup and WARNING log
- [ ] `test_get_catalog_entry_exact_match` — Exact provider/model/operation
- [ ] `test_get_catalog_entry_wildcard_model` — model=`*`
- [ ] `test_get_catalog_entry_partial_wildcard` — model=`gpt-4o*`
- [ ] `test_get_catalog_entry_no_match` — Returns None
- [ ] `test_record_usage_immediate_debit` — UsageRecord + BalanceTransaction created
- [ ] `test_record_usage_deferred` — UsageRecord created, NO BalanceTransaction
- [ ] `test_finalize_pipeline_billing` — Aggregates 3 deferred records, creates 1 debit, sets Job.charged_cost
- [ ] `test_debit_usage_row_locking` — Concurrent debits don't double-debit

**Integration Tests (write_log → billing):**
- [ ] `test_write_log_triggers_billing` — API_CALL + success=True → UsageRecord created
- [ ] `test_write_log_no_billing_on_failure` — success=False → no UsageRecord
- [ ] `test_write_log_deferred_billing` — set_billing_deferred(True) → no immediate debit
- [ ] `test_write_log_provider_cost_passthrough` — provider_cost flows to UsageRecord.raw_cost

**Token Estimator Tests:**
- [ ] `test_openai_image_tokens_standard` — Known resolution → expected tile count × 170 + 85
- [ ] `test_openai_image_tokens_gpt5` — Known resolution → pixels // 500
- [ ] `test_anthropic_image_tokens` — Known resolution → pixels // 750
- [ ] `test_estimate_prompt_tokens` — Known text → len // 4
- [ ] `test_estimate_embed_tokens_with_data` — tags + description → token estimate
- [ ] `test_estimate_embed_tokens_no_data` — Returns 350

**Golden Response Tests:**
- [ ] Replay a known fal.ai generation response with `result["cost"] = 0.035` → verify UsageRecord fields
- [ ] Replay a known OpenAI tagging response with 500 input / 200 output tokens → verify cost calculation
- [ ] Replay a pipeline (tag+describe+embed) → verify 3 UsageRecords + 1 BalanceTransaction + Job.charged_cost

---

## Appendix: Complete Cost Catalog Seed Data

All entries from migrations 029-038, reflecting the current state after all migrations:

### Token-Based Models

| Provider | Model | Operation | Input $/1M | Output $/1M | Call $ | Markup |
|----------|-------|-----------|-----------|------------|-------|--------|
| openai | gpt-4o | tag | 2.50 | 10.00 | 0 | 2.0x |
| openai | gpt-4o | describe | 2.50 | 10.00 | 0 | 2.0x |
| openai | gpt-4o | evaluate | 2.50 | 10.00 | 0 | 2.0x |
| openai | gpt-4o | evaluate_creative | 2.50 | 10.00 | 0 | 2.0x |
| openai | gpt-4o | summarize | 2.50 | 10.00 | 0 | 2.0x |
| openai | gpt-4o | summarize_eval | 2.50 | 10.00 | 0 | 2.0x |
| openai | gpt-4o | generate_prompts | 2.50 | 10.00 | 0 | 2.0x |
| openai | gpt-5.2 | tag | 1.75 | 14.00 | 0 | 2.0x |
| openai | gpt-5.2 | describe | 1.75 | 14.00 | 0 | 2.0x |
| openai | gpt-5.2 | evaluate | 1.75 | 14.00 | 0 | 2.0x |
| openai | gpt-5.2 | evaluate_creative | 1.75 | 14.00 | 0 | 2.0x |
| openai | gpt-5.2 | summarize | 1.75 | 14.00 | 0 | 2.0x |
| openai | gpt-5.2 | summarize_eval | 1.75 | 14.00 | 0 | 2.0x |
| openai | gpt-5.2 | generate_prompts | 1.75 | 14.00 | 0 | 2.0x |
| openai | gpt-4o-mini | expand_prompt | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-4o-mini | tag | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-4o-mini | describe | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-4o-mini | evaluate | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-4o-mini | evaluate_creative | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-4o-mini | summarize | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-4o-mini | summarize_eval | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-4o-mini | generate_prompts | 0.15 | 0.60 | 0 | 2.0x |
| openai | gpt-5-mini | expand_prompt | 0.25 | 2.00 | 0 | 2.0x |
| openai | gpt-5-mini | tag | 0.25 | 2.00 | 0 | 2.0x |
| openai | gpt-5-mini | describe | 0.25 | 2.00 | 0 | 2.0x |
| openai | gpt-5-mini | evaluate | 0.25 | 2.00 | 0 | 2.0x |
| openai | gpt-5-mini | evaluate_creative | 0.25 | 2.00 | 0 | 2.0x |
| openai | gpt-5-mini | summarize | 0.25 | 2.00 | 0 | 2.0x |
| openai | gpt-5-mini | summarize_eval | 0.25 | 2.00 | 0 | 2.0x |
| openai | gpt-5-mini | generate_prompts | 0.25 | 2.00 | 0 | 2.0x |
| openai | text-embedding-3-small | embed | 0.02 | 0 | 0 | 2.0x |
| anthropic | claude-sonnet-4-6 | tag | 3.00 | 15.00 | 0 | 2.0x |
| anthropic | claude-sonnet-4-6 | describe | 3.00 | 15.00 | 0 | 2.0x |
| anthropic | claude-sonnet-4-6 | evaluate | 3.00 | 15.00 | 0 | 2.0x |
| anthropic | claude-sonnet-4-6 | evaluate_creative | 3.00 | 15.00 | 0 | 2.0x |
| anthropic | claude-sonnet-4-6 | summarize | 3.00 | 15.00 | 0 | 2.0x |
| anthropic | claude-sonnet-4-6 | summarize_eval | 3.00 | 15.00 | 0 | 2.0x |
| anthropic | claude-sonnet-4-6 | generate_prompts | 3.00 | 15.00 | 0 | 2.0x |
| anthropic | claude-opus-4-6 | tag | 5.00 | 25.00 | 0 | 2.0x |
| anthropic | claude-opus-4-6 | describe | 5.00 | 25.00 | 0 | 2.0x |
| anthropic | claude-opus-4-6 | evaluate | 5.00 | 25.00 | 0 | 2.0x |
| anthropic | claude-opus-4-6 | evaluate_creative | 5.00 | 25.00 | 0 | 2.0x |
| anthropic | claude-opus-4-6 | summarize | 5.00 | 25.00 | 0 | 2.0x |
| anthropic | claude-opus-4-6 | summarize_eval | 5.00 | 25.00 | 0 | 2.0x |
| anthropic | claude-opus-4-6 | generate_prompts | 5.00 | 25.00 | 0 | 2.0x |
| anthropic | claude-haiku-4-5-20251001 | tag | 1.00 | 5.00 | 0 | 2.0x |
| anthropic | claude-haiku-4-5-20251001 | describe | 1.00 | 5.00 | 0 | 2.0x |
| anthropic | claude-haiku-4-5-20251001 | evaluate | 1.00 | 5.00 | 0 | 2.0x |
| anthropic | claude-haiku-4-5-20251001 | evaluate_creative | 1.00 | 5.00 | 0 | 2.0x |
| anthropic | claude-haiku-4-5-20251001 | summarize | 1.00 | 5.00 | 0 | 2.0x |
| anthropic | claude-haiku-4-5-20251001 | summarize_eval | 1.00 | 5.00 | 0 | 2.0x |
| anthropic | claude-haiku-4-5-20251001 | generate_prompts | 1.00 | 5.00 | 0 | 2.0x |
| anthropic | claude-3-haiku-20240307 | tag | 0.25 | 1.25 | 0 | 2.0x |
| anthropic | claude-3-haiku-20240307 | describe | 0.25 | 1.25 | 0 | 2.0x |
| anthropic | claude-3-haiku-20240307 | evaluate | 0.25 | 1.25 | 0 | 2.0x |
| anthropic | claude-3-haiku-20240307 | evaluate_creative | 0.25 | 1.25 | 0 | 2.0x |
| anthropic | claude-3-haiku-20240307 | summarize | 0.25 | 1.25 | 0 | 2.0x |
| anthropic | claude-3-haiku-20240307 | summarize_eval | 0.25 | 1.25 | 0 | 2.0x |
| anthropic | claude-3-haiku-20240307 | generate_prompts | 0.25 | 1.25 | 0 | 2.0x |
| fal | x-ai/grok-4-fast | tag | 0.20 | 0.50 | 0 | 2.0x |
| fal | x-ai/grok-4-fast | describe | 0.20 | 0.50 | 0 | 2.0x |
| fal | x-ai/grok-4-fast | evaluate | 0.20 | 0.50 | 0 | 2.0x |
| fal | x-ai/grok-4-fast | evaluate_creative | 0.20 | 0.50 | 0 | 2.0x |
| fal | x-ai/grok-4-fast | summarize_eval | 0.20 | 0.50 | 0 | 2.0x |
| fal | x-ai/grok-4-fast | generate_prompts | 0.20 | 0.50 | 0 | 2.0x |
| fal | qwen/qwen3-vl-235b-a22b-instruct | tag | 0.20 | 0.88 | 0 | 2.0x |
| fal | qwen/qwen3-vl-235b-a22b-instruct | describe | 0.20 | 0.88 | 0 | 2.0x |
| fal | qwen/qwen3-vl-235b-a22b-instruct | evaluate | 0.20 | 0.88 | 0 | 2.0x |
| fal | qwen/qwen3-vl-235b-a22b-instruct | evaluate_creative | 0.20 | 0.88 | 0 | 2.0x |
| fal | qwen/qwen3-vl-235b-a22b-instruct | summarize_eval | 0.20 | 0.88 | 0 | 2.0x |
| fal | qwen/qwen3-vl-235b-a22b-instruct | generate_prompts | 0.20 | 0.88 | 0 | 2.0x |
| fal | google/gemini-2.5-flash | tag | 0.30 | 2.50 | 0 | 2.0x |
| fal | google/gemini-2.5-flash | describe | 0.30 | 2.50 | 0 | 2.0x |
| fal | google/gemini-2.5-flash | evaluate | 0.30 | 2.50 | 0 | 2.0x |
| fal | google/gemini-2.5-flash | evaluate_creative | 0.30 | 2.50 | 0 | 2.0x |
| fal | google/gemini-2.5-flash | summarize_eval | 0.30 | 2.50 | 0 | 2.0x |
| fal | google/gemini-2.5-flash | generate_prompts | 0.30 | 2.50 | 0 | 2.0x |

### Per-Call Models

| Provider | Model (Endpoint) | Operation | Call $ | Markup |
|----------|-----------------|-----------|-------|--------|
| fal | fal-ai/flux-lora | generate | 0.035 | 2.0x |
| fal | fal-ai/flux/dev | generate | 0.025 | 2.0x |
| fal | fal-ai/qwen-image-2512/lora | generate | 0.035 | 2.0x |
| fal | fal-ai/qwen-image-2512 | generate | 0.02 | 2.0x |
| fal | fal-ai/nano-banana-pro | generate | 0.039 | 2.0x |
| fal | fal-ai/flux-lora-fast-training | train | 2.00 | 2.0x |
| fal | fal-ai/qwen-image-2512-trainer-v2 | train | 1.90 | 2.0x |
| fal | fal-ai/qwen-image-max-edit | edit | 0.075 | 2.0x |
| fal | fal-ai/kling-image/v2/image-to-image | edit | 0.028 | 2.0x |
| fal | fal-ai/wan-2.5/v1/image-to-image | edit | 0.05 | 2.0x |
| fal | fal-ai/grok-2-image/image-to-image | edit | 0.022 | 2.0x |
| fal | fal-ai/face-swap | edit | 0.009 | 2.0x |
| fal | fal-ai/nano-banana-pro/edit | edit | 0.039 | 2.0x |

### Customer-Facing Sparks Estimates (from catalog)

| Operation | Model | Est. Sparks/unit |
|-----------|-------|-----------------|
| Generate (flux-dev, no LoRA) | fal-ai/flux/dev | 50 |
| Generate (flux-dev, LoRA) | fal-ai/flux-lora | 70 |
| Generate (qwen-2.5, no LoRA) | fal-ai/qwen-image-2512 | 40 |
| Generate (qwen-2.5, LoRA) | fal-ai/qwen-image-2512/lora | 70 |
| Generate (nano-banana-pro) | fal-ai/nano-banana-pro | 78 |
| Train (flux-dev) | fal-ai/flux-lora-fast-training | 4000 |
| Train (qwen-2.5) | fal-ai/qwen-image-2512-trainer-v2 | 3800 |
| Edit (qwen-image-max-edit) | fal-ai/qwen-image-max-edit | 150 |
| Edit (kling-image) | fal-ai/kling-image/v2 | 56 |
| Edit (wan-25) | fal-ai/wan-2.5/v1 | 100 |
| Edit (grok-imagine) | fal-ai/grok-2-image | 44 |
| Edit (face-swap) | fal-ai/face-swap | 18 |
| Edit (nano-banana-pro-edit) | fal-ai/nano-banana-pro/edit | 78 |

---

## Appendix: Frontend Cost Display Inventory

| Component | File | What's Shown | Cost Type |
|-----------|------|-------------|-----------|
| Billing Page | `app/billing/page.tsx` | Balance, usage by op/provider, transaction history | Charged (sparks) |
| Describe All Dialog | `components/DescribeAllDialog.tsx:417` | `~{total} sparks ({per-image}/image)` | Estimated |
| Generate Page | `app/generate/page.tsx:472` | Per-image + total sparks + expand cost | Estimated |
| Generated Image Card | `components/GeneratedImageCard.tsx:130` | Spark badge on completed images | Charged |
| Jobs Page | `app/jobs/page.tsx:434` | Cost column per job | Charged |
| Vision Page | `app/vision/page.tsx:101` | Per-analysis cost by provider/model/mode | Estimated |
| Image Drawer | `components/ImageDrawer.tsx:117` | Per-image processing costs breakdown | Charged |
| Train Modal | `app/models/components/TrainLoraModal.tsx:137` | `~{sparks} sparks per training run` | Estimated |
| Admin Page | `app/admin/page.tsx` | Platform summary, user balances, billing logs, cost catalog | Both |

All cost displays use the amber Zap icon for visual consistency.
