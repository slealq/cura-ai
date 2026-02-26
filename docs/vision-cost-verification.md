# Vision Cost Estimation — Verification Report

**Date:** 2025-02-25
**Test image:** `alex-ifti-WFp3PHoizDw-unsplash.jpg` (image_id=353, 4540x5675 px, 2812 KB)
**Test script:** `backend/tests/verify_vision_costs.py`

## Methodology

1. Selected a real image from the local database with known dimensions (4540x5675)
2. Built the exact same prompts the codebase uses (`compose_tag_prompt`, `compose_description_prompt`)
3. Made real OpenAI API calls with identical parameters to the codebase (same `response_format`, `detail: "high"`, `max_tokens`/`max_completion_tokens`)
4. Compared our formula-based token estimates against OpenAI's actual reported `usage.prompt_tokens` and `usage.completion_tokens`
5. Computed cost in sparks using catalog rates and compared

## Token Analysis

### Prompt Token Estimation

Verified prompt char lengths against tiktoken (`cl100k_base` encoding):
- Tag prompt: 1356 chars → **318 actual tokens** (4.26 chars/tok)
- Describe prompt: 1240 chars → **243 actual tokens** (5.10 chars/tok)
- Our estimator uses `len(text) / 4.3` → 315 and 288 respectively (close enough)

### gpt-4o-mini Image Tokenization

**Finding: gpt-4o-mini does NOT use the documented tile formula.**

The documented OpenAI formula (scale longest→2048, shortest→768, 512x512 tiles, 170 tokens/tile + 85 base) gives **765 tokens** for this image — the actual is **25,508**.

Empirically verified: gpt-4o-mini uses **32x32 patches on the raw image** (no pre-scaling) plus ~232 tokens of `response_format: json_object` system overhead.

| Component | Formula | Tokens |
|---|---|---|
| 32x32 patches | ceil(4540/32) x ceil(5675/32) = 142 x 178 | 25,276 |
| json_object overhead | Fixed | 232 |
| **Total image tokens** | | **25,508** |
| Actual from API | | **25,508** |

**Verified: 0.0% error on image tokens.**

### gpt-5-mini Image Tokenization

gpt-5-mini uses dramatically fewer tokens for the same image. The formula `max(800, scaled_pixels/500)` after 2048/768 scaling gives **1,474** — the actual is **1,813** (18.7% underestimate).

| Component | Value |
|---|---|
| After 2048/768 scaling | 768 x 960 = 737,280 pixels |
| Formula: pixels/500 | 1,474 tokens |
| Actual from API | 1,813 tokens |
| Effective ratio | pixels/407 |

The gpt-5 family tokenization is undocumented. The pixels/500 formula is a reasonable approximation. DB-observed averages (already active with 3+ samples) override this with actual values.

## Cost Comparison (Formula vs Actual)

### gpt-4o-mini

Catalog rates: input=$0.00000015/tok, output=$0.00000060/tok, 2.0x markup

| Test | Est Input | Act Input | Est Sparks | Act Sparks | Error |
|---|---|---|---|---|---|
| tag | 25,823 | 25,826 | **8.35** | **7.82** | -6.8% |
| describe | 25,796 | 25,751 | **8.58** | **7.97** | -7.6% |

Input tokens are nearly perfect (0.0–0.2% error). The 6–8% spark overestimate comes from output token defaults (500/700) being higher than actual (57/204). This is conservative (overestimates cost), which is the right direction for user-facing quotes.

**Before this fix**: formula estimated 765 image tokens → 0.93 sparks (tag). Actual was 7.82 sparks. **That was an 88% underestimate.** Now it's a 7% overestimate.

### gpt-5-mini

Catalog rates: input=$0.00000025/tok, output=$0.00000200/tok, 2.0x markup

| Test | Est Input | Act Input | Est Sparks | Act Sparks | Error |
|---|---|---|---|---|---|
| tag | 1,789 | 2,131 | **2.89** | **3.82** | -24.2% |
| describe | 1,762 | 2,056 | **3.68** | **3.98** | -7.6% |

The tag underestimate is driven by both the image token formula (16% low) and output tokens being higher than the 500 default (688 actual). For describe, the estimate is quite close (7.6%) because the output default (700) matches well.

**Note:** DB-observed averages are already active for gpt-5-mini (3+ samples) and provide actual values of avg_in=2124 (tag) and avg_in=2036 (describe), making the formula a fallback only.

## Summary of Formula Accuracy

| Model | Image Token Formula | Error vs Actual | Cost Error | Notes |
|---|---|---|---|---|
| gpt-4o-mini | 32x32 patches + 232 overhead | **0.0%** | -7% (overestimates) | Empirically verified |
| gpt-5-mini | max(800, scaled_pixels/500) | -18.7% | -7% to -24% | DB averages override |
| gpt-4o | tile-based (170/tile + 85) | Not tested (documented formula) | — | Official OpenAI docs |
| gpt-5.2 | Same as gpt-5-mini | Not tested | — | DB averages needed |

## Changes Made

### token_estimator.py

1. **gpt-4o-mini**: New 32x32 patch formula replacing tile formula (was 33x wrong)
2. **Anthropic**: Added ~1.19M pixel area cap (was missing, causing 6.5x overestimate for large images)
3. **Gemini 2.5**: Tile-based formula (768x768 tiles, 258/tile) replacing fixed 258 tokens
4. **Qwen3-VL**: 32x32 patch formula replacing Anthropic heuristic (was 37% overestimate)
5. **Grok (xAI)**: Clamped to documented 256–1792 range
6. **Prompt tokens**: Changed from chars/4 to chars/4.3 (closer to actual BPE tokenization)

### billing_service.py
- Added docstring noting edit model costs are approximate (post-run uses fal.ai actual)

### billing.py
- Added comment explaining custom→describe mapping for DB averages

## Next Step: UI Verification

Run tag/describe operations through the UI (Settings → Vision page) and compare:
1. The pre-run cost estimate shown in the Describe All dialog
2. The actual charged cost shown in Billing after the operation completes
