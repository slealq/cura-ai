# Vision Models Reference

This document covers all vision models supported by the platform: how they calculate image token costs, what parameters they support, and how we compute billing estimates.

> **Last updated:** 2026-02-20

---

## Table of Contents

1. [Provider Overview](#provider-overview)
2. [OpenAI Vision Models](#openai-vision-models)
3. [Anthropic Vision Models](#anthropic-vision-models)
4. [fal.ai / OpenRouter Vision Models](#falai--openrouter-vision-models)
5. [Embedding Models](#embedding-models)
6. [Platform Cost Estimation](#platform-cost-estimation)
7. [Parameter Support Matrix](#parameter-support-matrix)

---

## Provider Overview

| Provider | Models Used | Endpoint | Auth |
|----------|------------|----------|------|
| OpenAI | gpt-4o, gpt-4o-mini, gpt-5-mini, gpt-5.2 | OpenAI Chat Completions API | `OPENAI_API_KEY` |
| Anthropic | claude-haiku-4-5-20251001, claude-sonnet-4-6, claude-opus-4-6 | Anthropic Messages API | `ANTHROPIC_API_KEY` |
| fal.ai (OpenRouter) | x-ai/grok-4-fast, qwen/qwen3-vl-235b-a22b-instruct, google/gemini-2.5-flash | `openrouter/router/vision` via fal.ai | `FAL_API_KEY` |

---

## OpenAI Vision Models

### Image Token Calculation

OpenAI uses **two different systems** depending on the model family. Token counts are returned in the API response's `prompt_tokens` field (image tokens are counted as input tokens).

#### System 1: Tile-Based with Detail Parameter

**Applies to:** gpt-4o, gpt-4o-mini, gpt-5, gpt-5.2

These models use a `detail` parameter (`"low"`, `"high"`, or `"auto"`).

**Low Detail Mode:** Fixed base token cost regardless of image size.

**High Detail Mode:**
1. Scale image to fit within 2048x2048 (maintain aspect ratio, only scale down)
2. Scale shortest side to 768px (maintain aspect ratio)
3. Count 512px tiles: `ceil(width/512) * ceil(height/512)`
4. Total tokens: `(num_tiles * tile_tokens) + base_tokens`

| Model | Base Tokens | Tile Tokens | Low Detail (Fixed) |
|-------|------------|-------------|-------------------|
| gpt-4o | 85 | 170 | 85 |
| gpt-4o-mini | 2833 | 5667 | 2833 |
| gpt-5 / gpt-5.2 | 70 | 140 | 70 |

> **Note on gpt-4o-mini:** Token counts are inflated (2833 base + 5667/tile) but per-token price is proportionally lower. Dollar cost ends up comparable to gpt-4o.

**Example calculations (gpt-4o, high detail):**
- 1024x1024: shortest to 768 -> 768x768. Tiles: 2x2=4. Tokens: (4*170)+85 = **765**
- 2048x4096: fit 2048 -> 1024x2048, shortest to 768 -> 768x1536. Tiles: 2x3=6. Tokens: (6*170)+85 = **1105**
- Any size, low detail: **85 tokens** (fixed)

#### System 2: Patch-Based (No Detail Parameter)

**Applies to:** gpt-4.1-mini, gpt-4.1-nano, gpt-5-mini, gpt-5-nano, o4-mini

These models have NO detail parameter. Every image is processed the same way.

1. Calculate raw patches: `ceil(width/32) * ceil(height/32)`
2. If raw patches > 1536, scale down to fit
3. Apply model-specific multiplier

| Model | Multiplier |
|-------|-----------|
| gpt-4.1-mini / gpt-5-mini | 1.62 |
| gpt-4.1-nano / gpt-5-nano | 2.46 |
| o4-mini | 1.72 |

**Example (gpt-5-mini):** 1024x1024 -> `ceil(1024/32)*ceil(1024/32)` = 1024 patches. Tokens: `1024 * 1.62` = **1659**

### Per-Token Pricing

| Model | Input ($/M tokens) | Output ($/M tokens) |
|-------|-------------------|-------------------|
| gpt-4o | $2.50 | $10.00 |
| gpt-4o-mini | $0.15 | $0.60 |
| gpt-5.2 | $1.75 | $14.00 |
| gpt-5-mini | $0.25 | $2.00 |

### Supported Parameters

| Parameter | Supported | Notes |
|-----------|-----------|-------|
| `temperature` | Yes | 0-2, default 1 |
| `max_tokens` / `max_completion_tokens` | Yes | Newer models (gpt-5*, gpt-4.1*) use `max_completion_tokens` |
| `detail` | Yes (tile-based models) | `"low"`, `"high"`, `"auto"`. We hardcode `"high"` |
| `response_format` | Yes | We use `{"type": "json_object"}` |
| `top_p` | Yes | 0-1, alternative to temperature |
| `frequency_penalty` | Yes | -2 to 2 |
| `presence_penalty` | Yes | -2 to 2 |

### Platform Implementation Notes

- **Detail mode:** Currently hardcoded to `"high"` in `openai_provider.py` (lines 100 and 208)
- **Temperature:** NOT currently passed (uses OpenAI default of 1)
- **Token counts:** Returned by OpenAI in response `usage.prompt_tokens` / `usage.completion_tokens`. We use these actual values for billing.
- **Token param selection:** `_token_limit_param()` sends `max_completion_tokens` for gpt-5*/gpt-4.1* models, `max_tokens` for others.

---

## Anthropic Vision Models

### Image Token Calculation

Anthropic uses a **pixel-area formula** (NOT tile-based):

```
tokens = (width * height) / 750
```

#### Resize Rules (Applied Before Token Calculation)

1. If long edge > 1568px, scale down preserving aspect ratio
2. If total pixels > ~1,192,464 (~1.19 megapixels), scale down
3. Maximum absolute limit: 8000x8000 (rejected outright)
4. If >20 images in request, limit drops to 2000x2000

#### Pre-billing Estimation Algorithm

```python
def estimate_anthropic_image_tokens(width: int, height: int) -> int:
    max_edge = 1568
    max_pixels = 1_192_464  # ~1092^2

    long_edge = max(width, height)
    if long_edge > max_edge:
        scale = max_edge / long_edge
        width = int(width * scale)
        height = int(height * scale)

    if width * height > max_pixels:
        scale = (max_pixels / (width * height)) ** 0.5
        width = int(width * scale)
        height = int(height * scale)

    return int((width * height) / 750)
```

**Optimal max sizes (not resized, ~1590 tokens each):**

| Aspect Ratio | Max Size |
|-------------|----------|
| 1:1 | 1092x1092 |
| 3:4 | 951x1268 |
| 2:3 | 896x1344 |
| 9:16 | 819x1456 |
| 1:2 | 784x1568 |

**Example calculations:**

| Image Size | Effective Size | Tokens |
|-----------|---------------|--------|
| 200x200 | 200x200 | ~54 |
| 1000x1000 | 1000x1000 | ~1,334 |
| 1092x1092 | 1092x1092 | ~1,590 |
| 2000x3000 | 1045x1568 | ~2,185 -> resized to ~1,590 |

### Per-Token Pricing

| Model | Input ($/M tokens) | Output ($/M tokens) |
|-------|-------------------|-------------------|
| claude-opus-4-6 | $5.00 | $25.00 |
| claude-sonnet-4-6 | $3.00 | $15.00 |
| claude-haiku-4-5-20251001 | $1.00 | $5.00 |

Image tokens are billed as standard input tokens — no separate image pricing tier.

### Supported Parameters

| Parameter | Supported | Notes |
|-----------|-----------|-------|
| `temperature` | Yes | 0-1 (NOT 0-2 like OpenAI) |
| `max_tokens` | Yes | Required (no default) |
| `top_p` | Yes | Mutually exclusive with temperature |
| `top_k` | Yes | Advanced use |
| `stop_sequences` | Yes | Custom stop strings |

### Platform Implementation Notes

- **Temperature:** NOT currently passed (uses Anthropic default of 1)
- **Token counts:** Returned in response `usage.input_tokens` / `usage.output_tokens`
- **Token counting API:** Anthropic offers free `POST /v1/messages/count_tokens` endpoint for exact pre-billing (not currently used)
- **Image placement:** Anthropic recommends images BEFORE text in messages for best results. Our code follows this pattern.

---

## fal.ai / OpenRouter Vision Models

### Billing Chain

```
Platform -> fal.ai -> OpenRouter -> Provider (xAI / DeepInfra)
```

fal.ai acts as a proxy to OpenRouter. The fal.ai API response includes a `usage` object with `prompt_tokens`, `completion_tokens`, `total_tokens`, and `cost` fields. The `cost` field contains the actual USD cost charged by fal.ai for the request — this is used as the primary billing source (see [Platform Implementation Notes](#platform-implementation-notes-2)).

### Model: x-ai/grok-4-fast

#### Image Token Calculation (Tile-Based)

| Property | Value |
|----------|-------|
| Tile size | 448x448 pixels |
| Tokens per tile | 256 |
| Formula | `(num_tiles + 1) * 256` |
| Maximum tiles | 6 |
| Token range per image | 512 (min, 1 tile) to 1,792 (max, 6 tiles) |
| Max image file size | 20 MiB |
| Supported formats | JPG/JPEG, PNG only |

**Example calculations:**
- 448x448 or smaller: 1 tile -> (1+1)*256 = 512 tokens
- 896x896: 2x2=4 tiles -> (4+1)*256 = 1,280 tokens
- Very large: capped at 6 tiles -> (6+1)*256 = 1,792 tokens

#### Pricing

| Metric | Price |
|--------|-------|
| Input tokens | $0.20/M ($0.0000002/token) |
| Output tokens | $0.50/M ($0.0000005/token) |
| Context window | 2,000,000 tokens |

### Model: qwen/qwen3-vl-235b-a22b-instruct

#### Image Token Calculation (Pixel-Patch)

| Property | Value |
|----------|-------|
| Patch size | 32x32 pixels |
| Formula | `ceil(width/32) * ceil(height/32)` |
| Min tokens per image | 4 |
| Max tokens per image | 16,384 |
| Resize behavior | Dimensions rounded to nearest multiple of 32 |

**Example calculations:**
- 512x512: `(512/32)*(512/32)` = 256 tokens
- 1024x1024: `(1024/32)*(1024/32)` = 1,024 tokens
- 2048x2048: `(2048/32)*(2048/32)` = 4,096 tokens

#### Pricing

| Metric | Price |
|--------|-------|
| Input tokens | $0.20/M ($0.0000002/token) |
| Output tokens | $0.88/M ($0.00000088/token) |
| Context window | 262,144 tokens |

> **Note:** Qwen3 VL has significantly higher output token cost ($0.88/M vs $0.50/M for Grok). Operations with verbose outputs (describe) will cost more.

### Model: google/gemini-2.5-flash

#### Image Token Calculation

Gemini 2.5 Flash uses a proprietary tokenizer. Google does not publicly document the exact tile/patch formula. From observed usage, a typical image consumes ~1,000-2,500 input tokens depending on resolution.

#### Pricing

Pricing sourced from [OpenRouter](https://openrouter.ai/google/gemini-2.5-flash):

| Metric | Price |
|--------|-------|
| Input tokens | $0.30/M ($0.0000003/token) |
| Output tokens | $2.50/M ($0.0000025/token) |
| Context window | 1,048,576 tokens |

> **Note:** Gemini 2.5 Flash has the highest output token cost of the three fal models ($2.50/M vs $0.88/M for Qwen and $0.50/M for Grok).

### fal.ai Markup

- OpenRouter does NOT mark up provider rates (charges 5.5% fee on credit purchases)
- fal.ai does NOT publicly disclose a specific markup
- fal.ai returns actual `cost` in API responses, which already includes their intermediary margin
- **Billing uses provider-reported cost:** When fal.ai returns a `cost` field, we use it directly as `raw_cost` and apply only the platform markup (default 2.0x). This replaced the previous approach of estimating from per-token rates with a 1.8x intermediary markup factor
- **Estimates remain catalog-based:** The `/billing/vision-costs` endpoint still uses per-token rates from the cost catalog (no provider-reported cost available pre-call)

### Supported Parameters (via fal.ai endpoint)

| Parameter | Supported | Notes |
|-----------|-----------|-------|
| `temperature` | Yes | 0-2, default 1 |
| `max_tokens` | Yes | Controls output length |
| `system_prompt` | Yes | System instructions |
| `reasoning` | Yes | Enable reasoning mode |
| `prompt` | Yes | Required |
| `image_urls` | Yes | Required, array of URLs or data URIs |
| `model` | Yes | Required, model identifier |

> **Important:** fal.ai only exposes `temperature`, `max_tokens`, `system_prompt`, and `reasoning`. Underlying model parameters like `top_p`, `seed` are NOT exposed through the fal.ai endpoint.

### Platform Implementation Notes

- **Temperature:** NOT currently passed (uses default)
- **Token counts:** Returned in fal.ai response as `usage.prompt_tokens` / `usage.completion_tokens`. Code uses fallback: `usage.get("prompt_tokens") or usage.get("input_tokens")` for forward compatibility.
- **Cost field:** fal.ai returns actual `cost` in response — this is passed as `provider_cost` to `write_log()` and used as the primary billing source. When present, raw cost = provider cost, and only `platform_markup` from the cost catalog is applied (default 2.0x). The `cost_source` field in UsageRecord detail is set to `"provider"`.
- **Cost catalog:** All three fal models (Grok 4 Fast, Qwen3 VL, Gemini 2.5 Flash) have cost catalog entries with OpenRouter per-token pricing. These are used for pre-call estimates and as fallback if `cost` is not returned.

---

## Embedding Models

Embeddings are always computed via OpenAI regardless of the vision provider.

| Model | Dimensions | Input ($/M tokens) | Output ($/M tokens) |
|-------|-----------|-------------------|-------------------|
| text-embedding-3-small | 1536 | $0.02 | $0 |

The embed operation concatenates `tags + description` into text and embeds it. Token count is purely text-based (no images).

---

## Platform Cost Estimation

### How Estimates Work Today

The `/billing/vision-costs` endpoint returns estimated spark costs per provider/model/mode. It uses:

1. **Fixed input token assumptions** per provider (NOT image-dimension-aware):
   - OpenAI: 1,200 tokens
   - Anthropic: 1,200 tokens
   - fal.ai: 2,200 tokens (Grok ~1,792 image + ~400 prompt)

2. **Fixed output token assumptions** per mode:
   - tag: 500 tokens
   - describe: 1,500 tokens
   - custom: 1,000 tokens

3. **Cost formula (estimates):**
   ```
   raw_cost = (input_tokens * cost_per_input_token) + (output_tokens * cost_per_output_token)
   charged_cost = raw_cost * platform_markup  # default 2.0x
   sparks = charged_cost * 1000
   ```

   > **Note:** For actual billing (not estimates), fal.ai models use the provider-reported `cost` field from the API response instead of computing from per-token rates. See [fal.ai Markup](#falai-markup).

### Known Accuracy Issues

1. **No per-image dimension awareness:** A 200x200 image and a 4000x4000 image are estimated at the same cost. For accurate pre-billing, we should compute per-image tokens based on actual dimensions.

### Resolved Issues

1. **fal.ai input tokens corrected:** Was 55,000 (from inflated billing data), now 2,200 (Grok ~1,792 image + ~400 prompt). The 55K figure was from fal.ai/OpenRouter internal processing overhead — actual model input is much lower.

2. **Combined operation estimates:** Describe, Describe All, and Vision dialogs now show tag + describe + embed combined cost.

3. **Cost catalog entries:** All fal models (Grok 4 Fast, Qwen3 VL 235B, Gemini 2.5 Flash) now have cost catalog entries.

4. **fal.ai billing uses provider-reported cost:** Previously, fal.ai billing read wrong token keys (`input_tokens`/`output_tokens` instead of `prompt_tokens`/`completion_tokens`) and computed cost from catalog per-token rates with a 1.8x intermediary markup. Now billing uses the `cost` field from the fal.ai API response directly, with only the platform markup (2.0x) applied. The 1.8x intermediary markup has been removed.

5. **Deferred pipeline billing:** Describe (tag + describe + embed) now creates one unified billing transaction instead of three separate debits. The UsageRecord detail includes per-operation breakdown (`cost_source: "provider"` for fal.ai calls, `cost_source: "catalog"` for embeddings).

### Recommended Improvements

1. **Dimension-based estimation:** Use actual image width/height from `ImageMetadata` to compute per-image token costs using the formulas documented above.

---

## Parameter Support Matrix

Summary of which parameters each provider/model supports, and what we should expose in the UI:

| Parameter | OpenAI | Anthropic | fal.ai (Grok/Qwen) | Expose in UI? |
|-----------|--------|-----------|---------------------|---------------|
| **temperature** | 0-2 (default 1) | 0-1 (default 1) | 0-2 (default 1) | Yes |
| **max_tokens (tag)** | Yes | Yes | Yes | Yes (per operation) |
| **max_tokens (describe)** | Yes | Yes | Yes | Yes (per operation) |
| **max_tokens (embed)** | N/A (text embedding) | N/A | N/A | No |
| **detail** (image quality) | low/high/auto | N/A | N/A | Future (OpenAI only) |
| **top_p** | Yes | Yes (mutex with temp) | No (not via fal.ai) | No (too advanced) |
| **frequency_penalty** | Yes | No | No | No |
| **presence_penalty** | Yes | No | No | No |
| **system_prompt** | Yes (via messages) | Yes (via system param) | Yes | Internal only |
| **response_format** | Yes (json_object) | No | No | Internal only |

### UI Parameter Exposure Strategy

**Settings Pane (global defaults):**
- Vision provider + model selection
- Temperature (0.0-2.0, clamped to 0-1 for Anthropic)
- Max tokens per operation: tagging, description, summarization

**Describe / Describe All dialog (per-invocation overrides):**
- Model selection
- Temperature
- Max tokens for tag operation
- Max tokens for describe operation
- All initialize from settings but can be overridden

**Vision pane:**
- Temperature
- Max tokens

---

## Pricing Sources

All per-token prices stored in the `cost_catalog` table are sourced from the provider's public pricing pages. These should be periodically verified as providers may change rates.

| Provider | Model | Source | Last Verified |
|----------|-------|--------|---------------|
| OpenAI | gpt-4o, gpt-4o-mini | https://platform.openai.com/pricing | 2025 |
| OpenAI | gpt-5-mini, gpt-5.2 | https://platform.openai.com/pricing | 2025 |
| OpenAI | text-embedding-3-small | https://platform.openai.com/pricing | 2025 |
| Anthropic | claude-haiku-4-5, sonnet-4-6, opus-4-6 | https://www.anthropic.com/pricing | 2025 |
| fal/OpenRouter | x-ai/grok-4-fast | https://openrouter.ai/x-ai/grok-4-fast | 2025 |
| fal/OpenRouter | qwen/qwen3-vl-235b-a22b-instruct | https://openrouter.ai/qwen/qwen3-vl-235b-a22b-instruct | Feb 2026 |
| fal/OpenRouter | google/gemini-2.5-flash | https://openrouter.ai/google/gemini-2.5-flash | Feb 2026 |

fal.ai does not publicly document their margin over OpenRouter rates. Actual billing uses the provider-reported `cost` from the API response (which already includes fal.ai's margin), so no intermediary markup factor is needed. Estimates use catalog per-token rates without any fal.ai-specific markup.
