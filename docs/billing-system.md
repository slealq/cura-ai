# Billing System - Complete Documentation

> **Purpose:** This document is the authoritative reference for all billing, cost prediction, cost calculation, and charging in the system. It covers every model, every operation, every task, and every place where cost is reflected. This document is the basis for developing and validating the billing system.
>
> **Last updated:** 2026-02-20
> **Branch:** u/slealq/dev_cycle4

---

## Table of Contents

1. [Currency & Core Concepts](#1-currency--core-concepts)
2. [Billing Architecture](#2-billing-architecture)
3. [Vision Models](#3-vision-models)
4. [Embedding Models](#4-embedding-models)
5. [Generation Models](#5-generation-models)
6. [Edit Models](#6-edit-models)
7. [Training Models](#7-training-models)
8. [Evaluation Operations](#8-evaluation-operations)
9. [Auxiliary Operations](#9-auxiliary-operations)
10. [Task Chaining & Compound Operations](#10-task-chaining--compound-operations)
11. [Cost Catalog Accuracy Audit](#11-cost-catalog-accuracy-audit)
12. [Cost Prediction Strategy](#12-cost-prediction-strategy)
13. [Where Costs Are Reflected in the UI](#13-where-costs-are-reflected-in-the-ui)
14. [Known Gaps & Issues](#14-known-gaps--issues)
15. [Validation Status](#15-validation-status)

---

## 1. Currency & Core Concepts

### Sparks Currency
- **1 spark = $0.001 USD** (1000 sparks = $1.00)
- All user-facing costs displayed in sparks
- Database stores `raw_cost` and `charged_cost` in **USD**; conversion to sparks happens at display time
- `UserBalance.balance` is stored in **sparks**

### Platform Markup
- Default: **2.0x** (100% markup on raw provider cost)
- Configurable per catalog entry via `platform_markup` column
- Formula: `charged_cost = raw_cost × platform_markup`
- Sparks: `sparks = charged_cost × 1000`

### Two Cost Calculation Paths

| Path | When Used | Formula |
|------|-----------|---------|
| **Catalog-based** | Token-billed models (OpenAI, Anthropic, OpenRouter vision) | `raw = (in_tokens × cost_per_in) + (out_tokens × cost_per_out) + cost_per_call` |
| **Provider-reported** | When `provider_cost` is passed (intended for fal.ai) | `raw = provider_cost (USD)` |

Both paths then apply: `charged = raw × markup`, `sparks = charged × 1000`

### Balance Enforcement
- All billable operations check `BillingService.check_balance_or_raise()` before execution
- Returns HTTP 402 (Payment Required) if balance <= 0
- Balance can go negative (no pre-check on exact amount, only > 0 check)

---

## 2. Billing Architecture

### Data Flow

```
Provider API Call
    ↓
Provider returns response (with usage/tokens or cost)
    ↓
write_log() called with input_tokens, output_tokens, provider_cost
    ↓
write_log() creates PipelineLog entry
    ↓
If success=True: calls record_usage_standalone()
    ↓
BillingService.record_usage() → _calculate_cost() → CostCatalog lookup
    ↓
Creates UsageRecord (raw_cost, charged_cost, detail JSON)
    ↓
If not deferred: creates BalanceTransaction (debit)
    ↓
If deferred: finalize_pipeline_billing() aggregates later
```

### Deferred Billing (Pipeline Operations)
Multi-step operations (tag + describe + embed) use deferred billing:
1. `set_billing_deferred(True)` at pipeline start
2. Each API call creates a `UsageRecord` but does NOT debit balance
3. After all steps complete: `finalize_pipeline_billing()` sums all `UsageRecord.charged_cost` values
4. Creates ONE `BalanceTransaction` for the total
5. Sets `Job.charged_cost` to total sparks

### Key Files

| File | Role |
|------|------|
| `backend/app/services/billing_service.py` | Core billing logic, cost calculation, balance management |
| `backend/app/services/billing_context.py` | Thread-local billing context (user_id, image_id, deferred flag) |
| `backend/app/services/log_service.py` | `write_log()` — triggers usage recording on success |
| `backend/app/services/token_estimator.py` | Formula-based token estimation for cost previews |
| `backend/app/api/billing.py` | REST endpoints for costs, balance, admin management |
| `backend/app/models/billing.py` | DB models: CostCatalog, UsageRecord, UserBalance, BalanceTransaction |

---

## 3. Vision Models

Vision models are used for **tagging** (extracting categorization tags) and **describing** (generating detailed reproduction descriptions) of images. They are also used in **custom** mode (user-provided prompts on the Vision page).

### 3.1 OpenAI GPT-4o Mini

| Attribute | Value |
|-----------|-------|
| **Model ID** | `gpt-4o-mini` |
| **Provider** | `openai` |
| **API** | OpenAI Chat Completions (`AsyncOpenAI.chat.completions.create`) |
| **API Parameters** | `model`, `messages` (text + base64 image URL with `detail: "high"`), `response_format: {"type": "json_object"}`, `max_tokens` |
| **API Response** | `usage.prompt_tokens`, `usage.completion_tokens`, `choices[0].message.content` |
| **Does API return cost?** | **No.** Returns token counts only. |
| **Charging model** | Per input token + per output token |
| **Official API pricing** | Input: $0.15/MTok ($0.00000015/tok), Output: $0.60/MTok ($0.0000006/tok) |
| **Our catalog rates** | Input: $0.00000015/tok, Output: $0.0000006/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, expand_prompt, generate_prompts, summarize, summarize_eval |
| **Actual cost calculation** | `charged = (prompt_tokens × 0.00000015 + completion_tokens × 0.0000006) × 2.0`; `sparks = charged × 1000` |
| **Cost prediction strategy** | DB average tokens (primary) → formula fallback. Formula known to be 49x too low for input tokens on this model. DB averages are accurate. |
| **Validated?** | **YES** — Compared estimate (22.5 sparks) vs actual (22.51 sparks) for tag+describe+embed pipeline. Match confirmed. |

### 3.2 OpenAI GPT-4o

| Attribute | Value |
|-----------|-------|
| **Model ID** | `gpt-4o` |
| **Provider** | `openai` |
| **API** | OpenAI Chat Completions |
| **API Parameters** | Same as gpt-4o-mini |
| **API Response** | `usage.prompt_tokens`, `usage.completion_tokens` |
| **Does API return cost?** | **No.** |
| **Charging model** | Per input token + per output token |
| **Official API pricing** | Input: $2.50/MTok ($0.0000025/tok), Output: $10.00/MTok ($0.00001/tok) |
| **Our catalog rates** | Input: $0.0000025/tok, Output: $0.00001/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval |
| **Actual cost calculation** | `charged = (prompt_tokens × 0.0000025 + completion_tokens × 0.00001) × 2.0` |
| **Cost prediction strategy** | DB average tokens (primary) → formula fallback |
| **Validated?** | **NO** — Not yet tested with real usage data comparison |

### 3.3 OpenAI GPT-5 Mini

| Attribute | Value |
|-----------|-------|
| **Model ID** | `gpt-5-mini` |
| **Provider** | `openai` |
| **API** | OpenAI Chat Completions |
| **API Parameters** | Same pattern. Uses `max_completion_tokens` (reasoning model) with 2x buffer since visible output is ~50% of limit due to internal reasoning. |
| **API Response** | `usage.prompt_tokens`, `usage.completion_tokens` (includes reasoning tokens) |
| **Does API return cost?** | **No.** |
| **Charging model** | Per input token + per output token |
| **Official API pricing** | Input: $0.25/MTok ($0.00000025/tok), Output: $2.00/MTok ($0.000002/tok) |
| **Our catalog rates** | Input: $0.00000025/tok, Output: $0.000002/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, expand_prompt, generate_prompts, summarize, summarize_eval |
| **Actual cost calculation** | `charged = (prompt_tokens × 0.00000025 + completion_tokens × 0.000002) × 2.0` |
| **Cost prediction strategy** | DB average tokens (primary) → formula fallback. Formula uses `max(800, scaled_pixels / 500)` for input token estimation, which is relatively accurate for gpt-5 family. |
| **Validated?** | **PARTIAL** — Formula estimation shown to be reasonable (~2100 vs observed ~2036-2124 input tokens). Full end-to-end cost validation not yet done. |

**IMPORTANT NOTE on reasoning models:** GPT-5 mini is a reasoning model. `usage.completion_tokens` includes internal reasoning tokens that are NOT visible in the output but ARE billed. The code correctly uses `max_completion_tokens` with a 2x buffer to accommodate this. This means output tokens can be significantly higher than the visible response text would suggest.

### 3.4 OpenAI GPT-5.2

| Attribute | Value |
|-----------|-------|
| **Model ID** | `gpt-5.2` |
| **Provider** | `openai` |
| **API** | OpenAI Chat Completions |
| **API Parameters** | Same as GPT-5 mini (reasoning model, uses `max_completion_tokens`) |
| **API Response** | `usage.prompt_tokens`, `usage.completion_tokens` |
| **Does API return cost?** | **No.** |
| **Charging model** | Per input token + per output token |
| **Official API pricing** | Input: $1.75/MTok ($0.00000175/tok), Output: $14.00/MTok ($0.000014/tok) |
| **Our catalog rates** | Input: $0.00000175/tok, Output: $0.000014/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval |
| **Note** | Missing `expand_prompt` catalog entry (only gpt-4o-mini and gpt-5-mini have it) |
| **Validated?** | **NO** |

### 3.5 Anthropic Claude 3 Haiku

| Attribute | Value |
|-----------|-------|
| **Model ID** | `claude-3-haiku-20240307` |
| **Provider** | `anthropic` |
| **API** | Anthropic Messages API (`AsyncAnthropic.messages.create`) |
| **API Parameters** | `model`, `max_tokens`, `messages` (with native image blocks: `type: "image"`, `source: {type: "base64", ...}`) |
| **API Response** | `usage.input_tokens`, `usage.output_tokens`, `content[0].text` |
| **Does API return cost?** | **No.** Returns token counts only. |
| **Image token formula** | `tokens = (width × height) / 750`. Image resized if long edge > 1568px. |
| **Charging model** | Per input token + per output token |
| **Official API pricing** | Input: $0.25/MTok ($0.00000025/tok), Output: $1.25/MTok ($0.00000125/tok) |
| **Our catalog rates** | Input: $0.00000025/tok, Output: $0.00000125/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval |
| **Validated?** | **NO** |

### 3.6 Anthropic Claude Haiku 4.5

| Attribute | Value |
|-----------|-------|
| **Model ID** | `claude-haiku-4-5-20251001` |
| **Provider** | `anthropic` |
| **API** | Same as above |
| **Official API pricing** | Input: $1.00/MTok ($0.000001/tok), Output: $5.00/MTok ($0.000005/tok) |
| **Our catalog rates** | Input: $0.000001/tok, Output: $0.000005/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval |
| **Validated?** | **NO** |

### 3.7 Anthropic Claude Sonnet 4.6

| Attribute | Value |
|-----------|-------|
| **Model ID** | `claude-sonnet-4-6` |
| **Provider** | `anthropic` |
| **API** | Same as above |
| **Official API pricing** | Input: $3.00/MTok ($0.000003/tok), Output: $15.00/MTok ($0.000015/tok) |
| **Our catalog rates** | Input: $0.000003/tok, Output: $0.000015/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval |
| **Validated?** | **NO** |

### 3.8 Anthropic Claude Opus 4.6

| Attribute | Value |
|-----------|-------|
| **Model ID** | `claude-opus-4-6` |
| **Provider** | `anthropic` |
| **API** | Same as above |
| **Official API pricing** | Input: $5.00/MTok ($0.000005/tok), Output: $25.00/MTok ($0.000025/tok) |
| **Our catalog rates** | Input: $0.000005/tok, Output: $0.000025/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval |
| **Validated?** | **NO** |

### 3.9 fal.ai / OpenRouter: Grok 4 Fast

| Attribute | Value |
|-----------|-------|
| **Model ID** | `x-ai/grok-4-fast` |
| **Provider** | `fal` (via OpenRouter) |
| **API** | fal.ai `openrouter/router/vision` endpoint → submits to OpenRouter |
| **API Parameters** | `image_urls` (data URIs), `prompt`, `model`, `max_tokens`, `temperature` (optional) |
| **API Response** | `output` (text), `usage: {prompt_tokens, completion_tokens, cost}` |
| **Does API return cost?** | **YES** — OpenRouter returns `usage.cost` in USD. The code passes this as `provider_cost`. |
| **Does API return tokens?** | **YES** — `usage.prompt_tokens` / `usage.completion_tokens` |
| **Charging model** | **Dual path:** If `usage.cost` is present, uses provider-reported cost. Otherwise falls back to per-token catalog rates. |
| **Official OpenRouter pricing** | Input: $0.20/MTok ($0.0000002/tok), Output: $0.50/MTok ($0.0000005/tok) |
| **Our catalog rates** | Input: $0.0000002/tok, Output: $0.0000005/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize_eval |
| **Note** | Does NOT have `summarize` operation (cluster summarization uses OpenAI/Anthropic only) |
| **Validated?** | **NO** |

**IMPORTANT:** The fal.ai OpenRouter vision endpoint returns `usage.cost` from OpenRouter. When this is present, the code uses the `provider_cost` path in `_calculate_cost()`, which means our catalog per-token rates are NOT used for actual cost calculation — only for cost PREDICTION. The actual charged cost = `provider_cost × markup`. This is different from direct OpenAI/Anthropic calls where we must calculate from tokens ourselves.

### 3.10 fal.ai / OpenRouter: Qwen3 VL 235B

| Attribute | Value |
|-----------|-------|
| **Model ID** | `qwen/qwen3-vl-235b-a22b-instruct` |
| **Provider** | `fal` (via OpenRouter) |
| **API** | Same as Grok 4 Fast |
| **Official OpenRouter pricing** | Input: $0.20/MTok ($0.0000002/tok), Output: $0.88/MTok ($0.00000088/tok) |
| **Our catalog rates** | Input: $0.0000002/tok, Output: $0.00000088/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize_eval |
| **Validated?** | **NO** |

### 3.11 fal.ai / OpenRouter: Gemini 2.5 Flash

| Attribute | Value |
|-----------|-------|
| **Model ID** | `google/gemini-2.5-flash` |
| **Provider** | `fal` (via OpenRouter) |
| **API** | Same as Grok 4 Fast |
| **Official OpenRouter pricing** | Input: $0.30/MTok ($0.0000003/tok), Output: $2.50/MTok ($0.0000025/tok) |
| **Our catalog rates** | Input: $0.0000003/tok, Output: $0.0000025/tok |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize_eval |
| **Validated?** | **NO** |

---

## 4. Embedding Models

### 4.1 OpenAI text-embedding-3-small

| Attribute | Value |
|-----------|-------|
| **Model ID** | `text-embedding-3-small` |
| **Provider** | `openai` |
| **API** | OpenAI Embeddings API (`AsyncOpenAI.embeddings.create`) |
| **API Parameters** | `model`, `input` (text string) |
| **API Response** | `usage.total_tokens` (single value, not split in/out), `data[0].embedding` (1536-dim vector) |
| **Does API return cost?** | **No.** |
| **Charging model** | Per input token only (embeddings have no output tokens) |
| **Official API pricing** | $0.02/MTok ($0.00000002/tok) |
| **Our catalog rates** | Input: $0.00000002/tok, Output: $0 |
| **Catalog match?** | **YES — matches exactly** |
| **Platform markup** | 2.0x |
| **Operations** | embed |
| **Actual cost calculation** | `charged = total_tokens × 0.00000002 × 2.0`; very small (~0.01 sparks per image) |
| **Cost prediction** | Default 350 tokens estimate, or `estimate_embed_tokens()` from actual tags + description text |
| **Validated?** | **YES** — Formula estimate (~350) vs observed (~339 tokens). Accurate. |

### 4.2 OpenAI text-embedding-3-large

| Attribute | Value |
|-----------|-------|
| **Model ID** | `text-embedding-3-large` |
| **Provider** | `openai` |
| **API** | Same as above |
| **Official API pricing** | $0.13/MTok ($0.00000013/tok) |
| **Our catalog rates** | **NOT IN CATALOG** |
| **Catalog match?** | **NO — MISSING** |
| **Gap** | If a user switches to text-embedding-3-large, costs will be recorded as $0 (catalog miss). Need to add catalog entry. |
| **Validated?** | **NO** |

---

## 5. Generation Models

All generation is via fal.ai. The fal.ai API uses `fal_client.submit()` + polling for completion.

### Critical Issue: fal.ai `cost` Field

**Research finding:** fal.ai does **NOT** return a `cost` field in API responses (confirmed via GitHub Issue #425 on fal-ai/fal repo). The code does `result.get("cost")` which will return `None`. This means:

- The `provider_cost` path is NEVER triggered for generation/training/edit operations
- Cost falls through to the catalog-based path
- Since generation models have `cost_per_call` in the catalog (not per-token), the catalog path works: `raw = cost_per_call`, `charged = raw × markup`
- **However**, catalog `cost_per_call` values are FIXED and don't account for dimension-based pricing (fal.ai charges per megapixel for Flux/Qwen generation)

### 5.1 Flux.1 Dev (Base)

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/flux/dev` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/flux/dev` via `fal_client.submit()` |
| **API Parameters** | `prompt`, `image_size: {width, height}`, `num_inference_steps`, `guidance_scale`, `seed`, `output_format: "png"`, `enable_safety_checker: False` |
| **API Response** | `images[].url`, `images[].width`, `images[].height`, `seed`, `has_nsfw_concepts` |
| **Does API return cost?** | **NO** — `result.get("cost")` returns None |
| **Does API return tokens?** | **No** — Generation has no tokens |
| **Charging model** | Per megapixel (fal.ai charges $0.025/megapixel) |
| **Official fal.ai pricing** | **$0.025 per megapixel** (1024×1024 = 1.049 MP → ~$0.026) |
| **Our catalog rates** | cost_per_call: $0.025 (FIXED) |
| **Catalog match?** | **APPROXIMATE** — Correct for ~1 megapixel images. Wrong for larger/smaller images. |
| **GAP** | Our catalog uses a fixed $0.025/call regardless of dimensions. fal.ai actually charges per megapixel. A 2048×2048 image (4.19 MP) would cost ~$0.105 from fal.ai but we'd charge based on $0.025. |
| **Platform markup** | 2.0x |
| **Operations** | generate |
| **Actual cost calculation** | Since `provider_cost` is None, falls to catalog: `raw = $0.025`, `charged = $0.05`, `sparks = 50` |
| **Cost prediction** | `GET /billing/generation-costs` returns fixed catalog cost × markup × 1000 = 50 sparks |
| **Validated?** | **NO** — Need to verify fal.ai dashboard charges vs our recorded costs |

### 5.2 Flux.1 Dev + LoRA

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/flux-lora` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/flux-lora` |
| **API Parameters** | Same as Flux base + `loras: [{path, scale}]` |
| **Official fal.ai pricing** | **$0.035 per megapixel** |
| **Our catalog rates** | cost_per_call: $0.035 (FIXED) |
| **Catalog match?** | **APPROXIMATE** — Same megapixel issue as above |
| **GAP** | Same as Flux base — fixed vs per-megapixel pricing |
| **Platform markup** | 2.0x |
| **Operations** | generate |
| **Validated?** | **NO** |

### 5.3 Qwen Image 2512 (Base)

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/qwen-image-2512` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/qwen-image-2512` |
| **API Parameters** | `prompt`, `image_size: {width, height}`, `num_inference_steps`, `guidance_scale`, `seed`, `output_format` |
| **Official fal.ai pricing** | **$0.02 per megapixel** |
| **Our catalog rates** | cost_per_call: $0.02 (FIXED) |
| **Catalog match?** | **APPROXIMATE** — Same megapixel issue |
| **Platform markup** | 2.0x |
| **Operations** | generate |
| **Validated?** | **NO** |

### 5.4 Qwen Image 2512 + LoRA

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/qwen-image-2512/lora` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/qwen-image-2512/lora` |
| **Official fal.ai pricing** | **$0.035 per megapixel** |
| **Our catalog rates** | cost_per_call: $0.035 (FIXED) |
| **Catalog match?** | **APPROXIMATE** |
| **Platform markup** | 2.0x |
| **Operations** | generate |
| **Validated?** | **NO** |

### 5.5 Nano Banana Pro

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/nano-banana-pro` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/nano-banana-pro` |
| **API Parameters** | `prompt`, `resolution` (e.g., "1K", "4K"), `aspect_ratio`, `safety_tolerance`, `enable_web_search`, `seed`, `output_format` — uses resolution/aspect_ratio instead of width/height |
| **Official fal.ai pricing** | **$0.15 per image** (flat). 4K resolution doubles to $0.30. Web search adds $0.015. |
| **Our catalog rates** | cost_per_call: $0.039 |
| **Catalog match?** | **NO — WRONG.** Our catalog says $0.039 but fal.ai charges $0.15/image. |
| **GAP — CRITICAL** | The catalog rate of $0.039 appears to be from an earlier pricing correction that was incorrect. fal.ai actually charges $0.15/image for nano-banana-pro. We are UNDERCHARGING by ~75%. Additionally, 4K resolution doubles the cost to $0.30, which our fixed rate doesn't account for. |
| **Platform markup** | 2.0x |
| **Operations** | generate |
| **Validated?** | **NO — NEEDS URGENT VALIDATION** |

---

## 6. Edit Models

All editing is via fal.ai. Same pattern: `fal_client.submit()` + polling.

**Same `cost` field issue:** fal.ai edit endpoints also do NOT return a `cost` field. `result.get("cost")` returns None. Falls to catalog-based calculation.

### 6.1 Qwen Image Max Edit

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/qwen-image-max/edit` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/qwen-image-max/edit` |
| **API Parameters** | `prompt`, `image_urls[]`, `num_images` (max 6), `negative_prompt`, `enable_prompt_expansion`, `enable_safety_checker`, `image_size`, `seed`, `output_format` |
| **Official fal.ai pricing** | **$0.075 per image** |
| **Our catalog rates** | cost_per_call: $0.075 |
| **Catalog match?** | **YES — matches exactly** |
| **GAP** | Cost is per OUTPUT image. If `num_images=3`, actual cost is $0.075 × 3 = $0.225. Our catalog charges $0.075 per API call regardless of `num_images`. **We undercharge when num_images > 1.** |
| **Platform markup** | 2.0x |
| **Operations** | edit |
| **Validated?** | **NO** |

### 6.2 Kling Image O3

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/kling-image/o3/image-to-image` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/kling-image/o3/image-to-image` |
| **API Parameters** | `prompt`, `image_urls[]`, `resolution` (1K/2K/4K), `aspect_ratio`, `num_images` (max 9), `seed`, `output_format` |
| **Official fal.ai pricing** | **$0.028 per image**. 4K doubles to $0.056. |
| **Our catalog rates** | cost_per_call: $0.028 |
| **Catalog match?** | **APPROXIMATE** — Correct for 1K/2K. Wrong for 4K. |
| **GAP** | Same num_images issue. Also 4K resolution doubles cost. |
| **Platform markup** | 2.0x |
| **Operations** | edit |
| **Validated?** | **NO** |

### 6.3 WAN 2.5 Preview

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/wan-25-preview/image-to-image` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/wan-25-preview/image-to-image` |
| **API Parameters** | `prompt`, `image_urls[]`, `negative_prompt`, `num_images` (max 4), `enable_safety_checker`, `seed`, `output_format` |
| **Official fal.ai pricing** | **$0.05 per image** |
| **Our catalog rates** | cost_per_call: $0.05 |
| **Catalog match?** | **YES — matches exactly** |
| **GAP** | Same num_images issue. |
| **Platform markup** | 2.0x |
| **Operations** | edit |
| **Validated?** | **NO** |

### 6.4 Grok Imagine Edit

| Attribute | Value |
|-----------|-------|
| **Model ID** | `xai/grok-imagine-image/edit` |
| **Provider** | `fal` |
| **API Endpoint** | `xai/grok-imagine-image/edit` |
| **API Parameters** | `prompt`, `image_url` (singular, not array), `num_images` (max 4), `seed`, `output_format` |
| **Official fal.ai pricing** | **$0.022 per image** ($0.02 output + $0.002 input processing) |
| **Our catalog rates** | cost_per_call: $0.022 |
| **Catalog match?** | **YES — matches exactly** |
| **GAP** | Same num_images issue. |
| **Platform markup** | 2.0x |
| **Operations** | edit |
| **Validated?** | **NO** |

### 6.5 Face Swap

| Attribute | Value |
|-----------|-------|
| **Model ID** | `half-moon-ai/ai-face-swap/faceswapimage` |
| **Provider** | `fal` |
| **API Endpoint** | `half-moon-ai/ai-face-swap/faceswapimage` |
| **API Parameters** | `source_face_url`, `target_image_url`, optional `enable_occlusion_prevention` |
| **API Response** | `image` (singular, not array) |
| **Official fal.ai pricing** | **$0.009 per call**. Occlusion prevention doubles to ~$0.018. |
| **Our catalog rates** | cost_per_call: $0.009 |
| **Catalog match?** | **YES** for basic. **NO** for occlusion prevention. |
| **GAP** | Occlusion prevention feature doubles cost but we always charge $0.009. |
| **Platform markup** | 2.0x |
| **Operations** | edit |
| **Validated?** | **NO** |

### 6.6 Nano Banana Pro Edit

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/nano-banana-pro/edit` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/nano-banana-pro/edit` |
| **API Parameters** | `prompt`, `image_urls[]`, `resolution`, `aspect_ratio`, `safety_tolerance`, `enable_web_search`, `num_images` (max 4), `seed`, `output_format` |
| **Official fal.ai pricing** | **$0.15 per image**. 4K doubles to $0.30. Web search adds $0.015. |
| **Our catalog rates** | cost_per_call: $0.039 |
| **Catalog match?** | **NO — WRONG.** Same issue as nano-banana-pro generation. Should be $0.15. |
| **GAP — CRITICAL** | Undercharging by ~75%. $0.039 vs actual $0.15. |
| **Platform markup** | 2.0x |
| **Operations** | edit |
| **Validated?** | **NO — NEEDS URGENT VALIDATION** |

---

## 7. Training Models

### 7.1 Flux LoRA Fast Training

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/flux-lora-fast-training` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/flux-lora-fast-training` |
| **API Parameters** | `images_data_url` (ZIP), `steps` (default 1000), `trigger_word`, `is_style` |
| **API Response** | `diffusers_lora_file.url` (LoRA weights), `config_file.url` |
| **Does API return cost?** | **NO** — `result.get("cost")` returns None |
| **Charging model** | Per training run. Scales linearly with steps (~$0.002/step implied). Base $2.00 for ~1000 steps. |
| **Official fal.ai pricing** | **~$2.00 per run** (at 1000 steps, scales with step count) |
| **Our catalog rates** | cost_per_call: $2.00 |
| **Catalog match?** | **APPROXIMATE** — Correct for 1000 steps. Wrong for other step counts. |
| **GAP** | If user trains with 2000 steps, actual cost is ~$4.00 but we charge $2.00. Training steps are configurable per-job. **We need step-based pricing, not flat per-call.** |
| **Platform markup** | 2.0x |
| **Operations** | train (recorded as `get_training_result` operation in write_log, which won't match catalog lookup for "train") |
| **BILLING BUG — CONFIRMED** | Two write_log calls happen: (1) `operation="start_training"` when job is submitted (success=True, triggers billing), (2) `operation="get_training_result"` when result is retrieved (success=True, triggers billing with provider_cost=None). **Neither operation name matches the catalog entry `"train"`.** Both record $0 cost. Additionally, `start_training` has no cost info at all, so it creates a spurious $0 UsageRecord. **All training is currently unbilled.** |
| **Cost prediction** | `GET /billing/training-costs` returns 4000 sparks (= $2.00 × 2.0x × 1000) — prediction is correct, but actual billing is $0. |
| **Validated?** | **NO — CONFIRMED BUG: training is unbilled** |

### 7.2 Qwen Image 2512 Trainer V2

| Attribute | Value |
|-----------|-------|
| **Model ID** | `fal-ai/qwen-image-2512-trainer-v2` |
| **Provider** | `fal` |
| **API Endpoint** | `fal-ai/qwen-image-2512-trainer-v2` |
| **API Parameters** | `image_data_url` (ZIP), `steps` (default 2000) — no trigger_word, no is_style |
| **Official fal.ai pricing** | **$0.00095 per step** (min 500 steps = $0.475 min). At 2000 steps = $1.90. |
| **Our catalog rates** | cost_per_call: $1.90 |
| **Catalog match?** | **APPROXIMATE** — Only correct for 2000 steps (the default). |
| **GAP** | Same as Flux training — need step-based pricing. At 1000 steps actual cost is $0.95, but we'd charge based on $1.90. |
| **Platform markup** | 2.0x |
| **Operations** | train |
| **BILLING BUG — CONFIRMED** | Same as Flux — `start_training` + `get_training_result` operations don't match catalog `train`. All training is unbilled. |
| **Validated?** | **NO — CONFIRMED BUG: training is unbilled** |

---

## 8. Evaluation Operations

LoRA evaluation (`evaluate_lora` task) triggers MULTIPLE separately-billed operations per evaluation. These are all vision-based operations charged per token.

### Operations triggered per evaluation run:

1. **generate_prompts** — Generate creative test prompts from training descriptions (1 API call)
2. **generate** — Generate images from prompts using the LoRA (N calls, N = number of reference + creative pairs)
3. **evaluate** — Compare original vs generated image pairs (N reference pairs)
4. **evaluate_creative** — Evaluate creative/novel generated images (M creative pairs)
5. **embed** — Generate embeddings for each generated image for similarity scoring (N+M calls)
6. **summarize_eval** — Generate overall assessment summary (1 API call)

### Per-operation billing:

| Operation | Provider | What it does | Billing |
|-----------|----------|-------------|---------|
| `generate_prompts` | openai/anthropic/fal | Generate test prompts | Per token (vision model) |
| `generate` | fal | Generate images | Per call (generation model, fixed cost) |
| `evaluate` | openai/anthropic/fal | Vision comparison (2 images) | Per token (2× image tokens — original + generated) |
| `evaluate_creative` | openai/anthropic/fal | Vision quality check (1 image) | Per token (1× image tokens) |
| `embed` | openai | Embedding for similarity | Per input token |
| `summarize_eval` | openai/anthropic/fal | Text summary of assessments | Per token (text only, no images) |

**Total evaluation cost** is highly variable depending on:
- Number of reference pairs (default typically 5-10)
- Number of creative pairs
- Which vision model is used
- Which generation model is used

**Current implementation note:** Evaluation uses deferred billing — each sub-operation records a UsageRecord but doesn't debit until finalization.

---

## 9. Auxiliary Operations

### 9.1 Expand Prompt

| Attribute | Value |
|-----------|-------|
| **Operation** | `expand_prompt` |
| **Purpose** | Expand user's short prompt into detailed generation prompt before image generation |
| **Provider** | `openai` |
| **Models** | `gpt-4o-mini` (default), `gpt-5-mini` (also has catalog entry) |
| **Trigger** | Frontend generation UI (before generate call) |
| **API** | OpenAI Chat Completions (text only, no images) |
| **Charging model** | Per input token + per output token |
| **Cost prediction** | `estimate_prompt_tokens("Expand this prompt...")` for input (~11 tokens), DB avg or default 200 for output. Very small cost (~0.3-0.5 sparks). |
| **Validated?** | **PARTIAL** — Cost prediction shown in generation page. Not validated against actual charges. |

### 9.2 Cluster Summarization

| Attribute | Value |
|-----------|-------|
| **Operation** | `summarize` |
| **Purpose** | Generate titles and bullet-point summaries for image clusters |
| **Providers** | `openai`, `anthropic` (NOT fal — uses direct API, not OpenRouter) |
| **Trigger** | `summarize_clusters` Celery task |
| **API** | Chat Completions / Messages API (text only, no images) |
| **Input** | Common cluster tags + sample image descriptions |
| **Charging model** | Per input token + per output token |
| **Note** | Not shown in any cost preview UI — charged after the fact |
| **Validated?** | **NO** |

---

## 10. Task Chaining & Compound Operations

### 10.1 Describe Pipeline (process_image_pipeline)

**User action:** Click "Describe" on an image, or "Describe All" on a folder.

**Tasks triggered (in sequence):**

| Step | Task | Operation | Provider | Cost Model | Deferred? |
|------|------|-----------|----------|------------|-----------|
| 1 | Tag | `tag` | openai/anthropic/fal | Per token | Yes |
| 2 | Describe | `describe` | openai/anthropic/fal | Per token | Yes |
| 3 | Embed | `embed` | openai (text-embedding-3-small) | Per input token | Yes |
| 4 | Finalize | `finalize_pipeline_billing()` | — | Aggregation | Creates single debit |

**Cost prediction formula (shown in UI before user clicks):**
```
estimated_total = tag_cost + describe_cost + embed_cost
```

For "Describe All" (batch), multiply by number of images:
```
batch_total = image_count × (tag_cost + describe_cost + embed_cost)
```

**Actual cost formula (after completion):**
```
job.charged_cost = sum(usage_record.charged_cost for each operation) × 1000  (sparks)
```

### 10.2 Tag Only

**User action:** Click "Tag" on an image.

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 | Tag | `tag` | openai/anthropic/fal | No |
| 2 | Re-embed (auto) | `embed` | openai | No (separate debit) |

**Note:** If the image already has a description, re-embedding is auto-triggered because the embedding depends on tags. This means "Tag" actually costs tag + embed (if description exists).

### 10.3 Describe Only

**User action:** Click "Describe" on an image.

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 | Describe | `describe` | openai/anthropic/fal | No |
| 2 | Re-embed (auto) | `embed` | openai | No (separate debit) |

**Note:** Same auto-embed as Tag. If tags exist, embedding is re-triggered.

### 10.4 Image Generation

**User action:** Click "Generate" on the generation page.

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 (optional) | Expand Prompt | `expand_prompt` | openai | No |
| 2 | Generate | `generate` | fal | No |

### 10.5 Image Edit

**User action:** Click "Edit" on the edit page.

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 | Edit | `edit` | fal | No |

### 10.6 LoRA Training

**User action:** Click "Train" on the models page.

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 | Start Training | `start_training` | fal | No billing (just submits) |
| 2 | Get Result | `get_training_result` | fal | No |

**Note:** Billing happens when `get_training_result` is called (after training completes). The `write_log` uses `operation="get_training_result"` — see billing bug in Section 7.

### 10.7 LoRA Evaluation

**User action:** Click "Evaluate" on a model.

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 | Generate prompts | `generate_prompts` | openai/anthropic/fal | Yes |
| 2 | Generate reference images | `generate` × N | fal | Yes |
| 3 | Generate creative images | `generate` × M | fal | Yes |
| 4 | Evaluate reference pairs | `evaluate` × N | openai/anthropic/fal | Yes |
| 5 | Evaluate creative images | `evaluate_creative` × M | openai/anthropic/fal | Yes |
| 6 | Embed generated images | `embed` × (N+M) | openai | Yes |
| 7 | Summarize assessments | `summarize_eval` | openai/anthropic/fal | Yes |
| 8 | Finalize | `finalize_pipeline_billing()` | — | Creates single debit |

### 10.8 Vision Analysis (Vision Page)

**User action:** Analyze an image on the Vision page.

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 | Tag/Describe/Custom | `tag` or `describe` | openai/anthropic/fal | No (direct, not deferred) |

Vision analysis is a single operation, NOT a pipeline. No auto-chaining. No embed. Billed immediately.

### 10.9 Cluster Summarization

**User action:** Summarize clusters (batch operation).

| Step | Task | Operation | Provider | Deferred? |
|------|------|-----------|----------|-----------|
| 1 | Summarize × N clusters | `summarize` | openai/anthropic | No |

---

## 11. Cost Catalog Accuracy Audit

Comparison of our catalog rates vs official API pricing (as of February 2026).

### Vision Token-Based Models

| Provider | Model | Our Input Rate | Official Rate | Match? | Our Output Rate | Official Rate | Match? |
|----------|-------|---------------|--------------|--------|----------------|--------------|--------|
| openai | gpt-4o-mini | $0.15/MTok | $0.15/MTok | YES | $0.60/MTok | $0.60/MTok | YES |
| openai | gpt-4o | $2.50/MTok | $2.50/MTok | YES | $10.00/MTok | $10.00/MTok | YES |
| openai | gpt-5-mini | $0.25/MTok | $0.25/MTok | YES | $2.00/MTok | $2.00/MTok | YES |
| openai | gpt-5.2 | $1.75/MTok | $1.75/MTok | YES | $14.00/MTok | $14.00/MTok | YES |
| openai | text-embedding-3-small | $0.02/MTok | $0.02/MTok | YES | — | — | — |
| anthropic | claude-3-haiku | $0.25/MTok | $0.25/MTok | YES | $1.25/MTok | $1.25/MTok | YES |
| anthropic | claude-haiku-4.5 | $1.00/MTok | $1.00/MTok | YES | $5.00/MTok | $5.00/MTok | YES |
| anthropic | claude-sonnet-4.6 | $3.00/MTok | $3.00/MTok | YES | $15.00/MTok | $15.00/MTok | YES |
| anthropic | claude-opus-4.6 | $5.00/MTok | $5.00/MTok | YES | $25.00/MTok | $25.00/MTok | YES |
| fal (OR) | grok-4-fast | $0.20/MTok | $0.20/MTok | YES | $0.50/MTok | $0.50/MTok | YES |
| fal (OR) | qwen3-vl-235b | $0.20/MTok | $0.20/MTok | YES | $0.88/MTok | $0.88/MTok | YES |
| fal (OR) | gemini-2.5-flash | $0.30/MTok | $0.30/MTok | YES | $2.50/MTok | $2.50/MTok | YES |

**All vision token rates are CORRECT.**

### Generation Per-Call Models

| Model | Our Rate | Official Rate | Match? | Issue |
|-------|----------|--------------|--------|-------|
| flux/dev | $0.025/call | $0.025/MP | APPROX | Per-megapixel, not per-call |
| flux-lora | $0.035/call | $0.035/MP | APPROX | Per-megapixel, not per-call |
| qwen-image-2512 | $0.02/call | $0.02/MP | APPROX | Per-megapixel, not per-call |
| qwen-image-2512/lora | $0.035/call | $0.035/MP | APPROX | Per-megapixel, not per-call |
| nano-banana-pro | $0.039/call | **$0.15/image** | **WRONG** | Undercharging by ~75% |

### Edit Per-Call Models

| Model | Our Rate | Official Rate | Match? | Issue |
|-------|----------|--------------|--------|-------|
| qwen-image-max-edit | $0.075/call | $0.075/image | YES | num_images multiplier missing |
| kling-image | $0.028/call | $0.028/image | YES | 4K doubles cost; num_images |
| wan-25 | $0.05/call | $0.05/image | YES | num_images multiplier missing |
| grok-imagine-edit | $0.022/call | $0.022/image | YES | num_images multiplier missing |
| face-swap | $0.009/call | $0.009/call | YES | Occlusion doubles cost |
| nano-banana-pro-edit | $0.039/call | **$0.15/image** | **WRONG** | Undercharging by ~75% |

### Training Per-Call Models

| Model | Our Rate | Official Rate | Match? | Issue |
|-------|----------|--------------|--------|-------|
| flux-lora-fast-training | $2.00/call | ~$2.00/1000 steps | APPROX | Scales with steps |
| qwen-image-2512-trainer | $1.90/call | $0.00095/step × 2000 = $1.90 | APPROX | Scales with steps |

---

## 12. Cost Prediction Strategy

### Vision Operations (tag, describe, custom)

**Strategy: DB averages (primary) → formula (fallback)**

1. Query `AVG(input_tokens)` and `AVG(output_tokens)` from `usage_records` for the specific provider/model/operation combo
2. If >= 3 samples exist: use DB averages for both input and output tokens
3. If < 3 samples: fall back to formula-based estimation:
   - **Input tokens:** `estimate_vision_input_tokens(provider, model, width, height, prompt_text)`
     - OpenAI gpt-4o family: tile formula (known to be ~49x too low for gpt-4o-mini)
     - OpenAI gpt-5 family: `max(800, scaled_pixels / 500)` (accurate)
     - Anthropic: `(width × height) / 750` (matches official formula)
     - fal/OpenRouter: `(width × height) / 750` (approximation)
   - **Output tokens:** `DEFAULT_OUTPUT_TOKENS` dict: tag=500, describe=700, custom=600
4. Calculate: `sparks = (in_tokens × in_rate + out_tokens × out_rate) × markup × 1000`

**Endpoint:** `POST /billing/vision-costs` (with width/height or folder_id), `GET /billing/vision-costs` (default 1024×1024)

### Embed Operations

**Strategy: Static estimate**
- Default 350 tokens if no tags/description available
- `estimate_embed_tokens(tags, description)` from actual text when available
- Cost is negligible (~0.01 sparks)

### Generation Operations

**Strategy: Fixed catalog lookup**
- `GET /billing/generation-costs` returns `cost_per_call × markup × 1000` for each model
- Does NOT account for image dimensions (megapixel pricing)
- Expand prompt cost estimated separately

### Edit Operations

**Strategy: Fixed catalog lookup**
- `GET /billing/edit-costs` returns `cost_per_call × markup × 1000` for each model
- Does NOT account for `num_images` or resolution (4K doubling)

### Training Operations

**Strategy: Fixed catalog lookup**
- `GET /billing/training-costs` returns `cost_per_call × markup × 1000` for each model
- Does NOT account for step count variations

---

## 13. Where Costs Are Reflected in the UI

### 13.1 Cost Preview (Before Action)

| Location | Component | What's Shown | API Endpoint | Accuracy |
|----------|-----------|-------------|-------------|----------|
| Image Drawer → Describe button | `ImageDrawer.tsx` | Per-model tag + describe + embed cost | `POST /billing/vision-costs` (with image dimensions) | Good (DB averages) |
| Describe All dialog | `DescribeAllDialog.tsx` | Total = image_count × per-image cost | `POST /billing/vision-costs` (with folder_id) | Good (folder avg dims) |
| Vision page → analysis | `vision/page.tsx` | Per-model tag/describe/custom cost | `POST /billing/vision-costs` (with source dims) | Good (DB averages) |
| Generate page | `generate/page.tsx` | Per-image generation cost + expand prompt | `GET /billing/generation-costs` | Approximate (fixed per-call) |
| Edit page | `edit/page.tsx` | Per-call edit cost by model | `GET /billing/edit-costs` | Approximate (fixed per-call) |
| Models page → Train | `models/page.tsx` | Per-job training cost by base model | `GET /billing/training-costs` | Approximate (fixed per-call) |

### 13.2 Post-Action Cost Display

| Location | What's Shown | Source |
|----------|-------------|--------|
| Job completion toast | Charged sparks for the job | `Job.charged_cost` |
| Billing page → Balance | Current spark balance | `GET /billing/balance` |
| Billing page → Transactions | Credit/debit history with descriptions | `GET /billing/transactions` |
| Billing page → Usage | Totals by operation and provider | `GET /billing/usage` |
| Admin → Platform Summary | Total raw/charged, margin, by provider/operation | `GET /billing/admin/summary` |
| Admin → Billing Logs | Per-record detail with cost breakdown | `GET /billing/admin/logs` |
| Admin → Cost Catalog | Editable rate table | `GET /billing/admin/catalog` |
| Admin → User Balances | Per-user balance and total spent | `GET /billing/admin/users` |

### 13.3 Image-Level Cost Display

| Location | What's Shown | Source |
|----------|-------------|--------|
| Image Drawer → Cost breakdown | Per-operation sparks for this image's last describe | `GET /images/{id}/cost-breakdown` |

---

## 14. Known Gaps & Issues

### CRITICAL

1. **Nano Banana Pro pricing is WRONG** — Catalog says $0.039 but fal.ai charges $0.15/image. Affects both generation ($0.039 vs $0.15) and edit ($0.039 vs $0.15). Undercharging by ~75%.

2. **fal.ai does NOT return `cost` in API responses** — Code does `result.get("cost")` expecting a USD value, but it returns `None`. This means the `provider_cost` path is NEVER triggered for generation/training/edit. Instead, cost falls to the catalog-based path using `cost_per_call`. This actually works for most models (catalog has correct rates), but it means we're NOT using provider-reported costs — we're using our own catalog rates.

3. **Training is completely unbilled (CONFIRMED BUG)** — Two `write_log()` calls happen per training job: `operation="start_training"` (on submission) and `operation="get_training_result"` (on result retrieval). Both have `success=True` and are `API_CALL` category, so both trigger `record_usage_standalone()`. However, the catalog entry uses `operation="train"`. Neither `"start_training"` nor `"get_training_result"` matches any catalog entry, so both record $0. Additionally, `start_training` creates a spurious $0 UsageRecord even though it's just a job submission with no cost. **Fix needed:** Change `get_training_result`'s `operation` to `"train"`, and change `start_training`'s category to something other than `API_CALL` (or don't log `success=True`) to prevent the spurious billing record.

### HIGH

4. **Generation pricing is per-megapixel, not per-call** — Flux and Qwen generation models charge per megapixel. Our catalog uses fixed `cost_per_call`. For 1024×1024 images (~1 MP), the approximation is close. For larger images, we significantly undercharge.

5. **Edit pricing doesn't account for `num_images`** — fal.ai charges per output image. Our catalog charges per API call. If `num_images=4`, actual cost is 4× our charge.

6. **Training pricing doesn't account for step count** — Both trainers charge based on steps. Our catalog uses fixed per-call rates that only match default step counts.

7. **text-embedding-3-large missing from catalog** — If a user selects this model, costs are recorded as $0.

### MEDIUM

8. **4K resolution pricing not handled** — Kling-image and nano-banana-pro charge double for 4K resolution. Our catalog doesn't differentiate.

9. **Face swap occlusion prevention pricing** — Doubles cost from $0.009 to $0.018. Not tracked.

10. **Web search add-on pricing** — Nano Banana Pro adds $0.015 for web search. Not tracked.

11. **OpenRouter cost vs catalog cost divergence** — For fal.ai OpenRouter vision calls, the code passes both `provider_cost=usage.get("cost")` AND token counts. When OpenRouter returns a cost, the provider-reported path is used (ignoring catalog rates). This means actual charged cost may differ from what the catalog would calculate. Not necessarily a bug, but a data consistency note.

12. **GPT-5.2 missing `expand_prompt` catalog entry** — Only gpt-4o-mini and gpt-5-mini have expand_prompt entries. If expand_prompt were ever routed to gpt-5.2, it would be charged $0.

13. **No cost preview for LoRA evaluation** — The evaluation page doesn't show estimated cost before starting. Evaluations can be expensive (multiple generation + vision calls).

### LOW

14. **Formula-based estimation is very inaccurate for gpt-4o-mini** — The OpenAI tile formula gives ~765 tokens for 1024×1024 but actual usage is ~37,160 tokens. This only affects cost prediction for models without DB data.

15. **Balance can go negative** — The system only checks `balance > 0` before operations, not whether the balance is sufficient for the estimated cost. A user with 1 spark balance can trigger a 100-spark operation.

---

## 15. Validation Status

### Fully Validated

| Model | Operation | Method | Result |
|-------|-----------|--------|--------|
| gpt-4o-mini | tag+describe+embed | Compared estimate vs actual usage records | Estimate 22.5 vs actual 22.51 sparks. PASS |
| text-embedding-3-small | embed | Compared formula vs observed tokens | ~350 estimate vs ~339 actual. PASS |
| gpt-5-mini | tag (formula) | Compared formula vs observed input tokens | ~2100 estimate vs ~2036-2124 actual. PASS |

### Not Yet Validated

| Category | Models | Priority |
|----------|--------|----------|
| Vision (OpenAI) | gpt-4o, gpt-5.2 | Medium |
| Vision (Anthropic) | claude-3-haiku, claude-haiku-4.5, claude-sonnet-4.6, claude-opus-4.6 | Medium |
| Vision (fal/OpenRouter) | grok-4-fast, qwen3-vl-235b, gemini-2.5-flash | Medium |
| Generation | flux/dev, flux-lora, qwen-image-2512, qwen-image-2512/lora | High |
| Generation | nano-banana-pro | **CRITICAL** (known wrong pricing) |
| Edit | All 6 edit models | High |
| Training | flux-lora-fast-training, qwen-image-2512-trainer | **CRITICAL** (suspected billing bug) |
| Evaluation | Full evaluation pipeline | Medium |
| Auxiliary | expand_prompt, summarize | Low |

### Validation Procedure

To validate a model's billing:

1. **Check catalog rate** against official API pricing page
2. **Run the operation** on a test image/prompt
3. **Check `usage_records`** table for the recorded input_tokens, output_tokens, raw_cost, charged_cost
4. **Check `balance_transactions`** for the corresponding debit
5. **For fal.ai models:** Check the fal.ai dashboard for the actual charge, compare with our recorded cost
6. **For token-based models:** Verify that `raw_cost = in_tokens × in_rate + out_tokens × out_rate` matches the usage_record values
7. **For provider-cost models:** Verify the flow: `provider_cost` → `raw_cost` → `charged_cost` with correct markup
8. **Record results** in this document

---

## Appendix A: Complete Cost Catalog (Current)

### OpenAI Models

| Model | Operation | Input Rate ($/tok) | Output Rate ($/tok) | Per-Call ($) | Markup |
|-------|-----------|-------------------|--------------------|-----------|----|
| gpt-4o-mini | tag, describe, evaluate, evaluate_creative, expand_prompt, generate_prompts, summarize, summarize_eval | 0.00000015 | 0.0000006 | — | 2.0x |
| gpt-4o | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval | 0.0000025 | 0.00001 | — | 2.0x |
| gpt-5-mini | tag, describe, evaluate, evaluate_creative, expand_prompt, generate_prompts, summarize, summarize_eval | 0.00000025 | 0.000002 | — | 2.0x |
| gpt-5.2 | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval | 0.00000175 | 0.000014 | — | 2.0x |
| text-embedding-3-small | embed | 0.00000002 | 0 | — | 2.0x |

### Anthropic Models

| Model | Operation | Input Rate ($/tok) | Output Rate ($/tok) | Markup |
|-------|-----------|-------------------|--------------------|----|
| claude-3-haiku-20240307 | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize, summarize_eval | 0.00000025 | 0.00000125 | 2.0x |
| claude-haiku-4-5-20251001 | (same ops) | 0.000001 | 0.000005 | 2.0x |
| claude-sonnet-4-6 | (same ops) | 0.000003 | 0.000015 | 2.0x |
| claude-opus-4-6 | (same ops) | 0.000005 | 0.000025 | 2.0x |

### fal.ai OpenRouter Vision Models

| Model | Operation | Input Rate ($/tok) | Output Rate ($/tok) | Markup |
|-------|-----------|-------------------|--------------------|----|
| x-ai/grok-4-fast | tag, describe, evaluate, evaluate_creative, generate_prompts, summarize_eval | 0.0000002 | 0.0000005 | 2.0x |
| qwen/qwen3-vl-235b-a22b-instruct | (same ops) | 0.0000002 | 0.00000088 | 2.0x |
| google/gemini-2.5-flash | (same ops) | 0.0000003 | 0.0000025 | 2.0x |

### fal.ai Generation Models

| Model | Operation | Per-Call ($) | Markup | Note |
|-------|-----------|-------------|--------|------|
| fal-ai/flux/dev | generate | 0.025 | 2.0x | Should be per-megapixel |
| fal-ai/flux-lora | generate | 0.035 | 2.0x | Should be per-megapixel |
| fal-ai/qwen-image-2512 | generate | 0.02 | 2.0x | Should be per-megapixel |
| fal-ai/qwen-image-2512/lora | generate | 0.035 | 2.0x | Should be per-megapixel |
| fal-ai/nano-banana-pro | generate | 0.039 | 2.0x | **WRONG — should be 0.15** |

### fal.ai Edit Models

| Model | Operation | Per-Call ($) | Markup | Note |
|-------|-----------|-------------|--------|------|
| fal-ai/qwen-image-max/edit | edit | 0.075 | 2.0x | Per-image, not per-call |
| fal-ai/kling-image/o3/image-to-image | edit | 0.028 | 2.0x | 4K doubles cost |
| fal-ai/wan-25-preview/image-to-image | edit | 0.05 | 2.0x | Per-image |
| xai/grok-imagine-image/edit | edit | 0.022 | 2.0x | Per-image |
| half-moon-ai/ai-face-swap/faceswapimage | edit | 0.009 | 2.0x | Occlusion doubles |
| fal-ai/nano-banana-pro/edit | edit | 0.039 | 2.0x | **WRONG — should be 0.15** |

### fal.ai Training Models

| Model | Operation | Per-Call ($) | Markup | Note |
|-------|-----------|-------------|--------|------|
| fal-ai/flux-lora-fast-training | train | 2.00 | 2.0x | Scales with steps |
| fal-ai/qwen-image-2512-trainer-v2 | train | 1.90 | 2.0x | $0.00095/step |
