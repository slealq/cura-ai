# Model catalog

Catalog snapshot: 2026-10-30. Prices below are estimates in USD. Provider-reported cost takes precedence for billing and catalog markup applies. The paid smoke matrix is recorded in [live verification](model-catalog-live-verification.json). Billing applies a 2× platform markup to provider costs or catalog estimates.

## Language and vision

All entries support text and vision through fal OpenRouter. Rates are per million input/output tokens. Source: [OpenRouter model directory](https://openrouter.ai/api/v1/models).

| Model | Vendor | Input / output | Temperature |
|---|---|---:|---|
| `anthropic/claude-haiku-5.5` | anthropic | $0.1 / $0.5 | no |
| `anthropic/claude-sonnet-5.5` | anthropic | $2 / $10 | no |
| `anthropic/claude-opus-5.5` | anthropic | $4 / $20 | no |
| `openai/gpt-6-luna` | openai | $0.1 / $0.5 | no |
| `openai/gpt-6.1-terra` | openai | $1 / $5 | no |
| `openai/gpt-6.1-sol` | openai | $2 / $10 | no |
| `openai/gpt-6-astra` | openai | $10 / $50 | no |
| `google/gemini-3.5-flash-lite` | google | $0.3 / $2.5 | yes |
| `google/gemini-3.8-flash` | google | $0.825 / $4.125 | yes |
| `google/gemini-4-argon` | google | $2 / $10 | yes |
| `x-ai/grok-4.3` | x-ai | $1.25 / $2.5 | yes |
| `deepseek/deepseek-v4.1-flash` | deepseek | $0.045 / $0.5 | yes |
| `moonshotai/kimi-k3.1-pro` | moonshotai | $2 / $10 | no |
| `z-ai/glm-5.3-flash` | z-ai | $0.018 / $0.1402 | yes |
| `z-ai/glm-5.3-flashx` | z-ai | $0.37 / $1.25 | yes |
| `minimax/minimax-m3.1-flash` | minimax | $0.15 / $0.6 | yes |
| `minimax/minimax-m3` | minimax | $0.3 / $1.2 | yes |

Long-prompt tiers for Haiku, GPT, and Grok models are applied to token estimates and fallback charges at the specified input threshold; reported provider cost remains authoritative. MiniMax Flash uses the higher estimate for time-dependent pricing.

## Generation and editing

Prices are default-option estimates per call. Variable price tables and LoRA rates are in the catalog. Endpoint links are fal model pages.

| Kind | Key | Vendor | Endpoint | Default price |
|---|---|---|---|---:|
| generate | `nano-banana-pro` | google | [fal-ai/nano-banana-pro](https://fal.ai/models/fal-ai/nano-banana-pro) | $0.15 |
| generate | `nano-banana-lite` | google | [google/nano-banana-lite](https://fal.ai/models/google/nano-banana-lite) | $0.042 |
| generate | `gpt-image-2.5-flare` | openai | [openai/gpt-image-2.5/flare/text-to-image](https://fal.ai/models/openai/gpt-image-2.5/flare/text-to-image) | $0.05268 |
| generate | `gpt-image-2.5-sunburst` | openai | [openai/gpt-image-2.5/sunburst/text-to-image](https://fal.ai/models/openai/gpt-image-2.5/sunburst/text-to-image) | $0.05268 |
| generate | `gpt-image-2` | openai | [openai/gpt-image-2](https://fal.ai/models/openai/gpt-image-2) | $0.211 |
| generate | `flux-3` | black-forest-labs | [blackforestlabs/flux-3/text-to-image](https://fal.ai/models/blackforestlabs/flux-3/text-to-image) | $0.048 |
| generate | `flux-3-klein` | black-forest-labs | [blackforestlabs/flux-3/klein/text-to-image](https://fal.ai/models/blackforestlabs/flux-3/klein/text-to-image) | $0.009 |
| generate | `flux-2-pro` | black-forest-labs | [fal-ai/flux-2-pro](https://fal.ai/models/fal-ai/flux-2-pro) | $0.03 |
| generate | `flux-2-max` | black-forest-labs | [fal-ai/flux-2-max](https://fal.ai/models/fal-ai/flux-2-max) | $0.07 |
| generate | `flux-2` | black-forest-labs | [fal-ai/flux-2](https://fal.ai/models/fal-ai/flux-2) | $0.012 |
| generate | `qwen-image-2512` | alibaba | [fal-ai/qwen-image-2512](https://fal.ai/models/fal-ai/qwen-image-2512) | $0.02 |
| generate | `seedream-5-pro` | bytedance | [bytedance/seedream/v5/pro/text-to-image](https://fal.ai/models/bytedance/seedream/v5/pro/text-to-image) | $0.135 |
| generate | `seedream-5-flash` | bytedance | [bytedance/seedream/v5/flash/text-to-image](https://fal.ai/models/bytedance/seedream/v5/flash/text-to-image) | $0.027 |
| generate | `qwen-image-3` | alibaba | [alibaba/qwen-image-3/text-to-image](https://fal.ai/models/alibaba/qwen-image-3/text-to-image) | $0.04 |
| generate | `grok-imagine-quality` | xai | [xai/grok-imagine-image/quality/text-to-image](https://fal.ai/models/xai/grok-imagine-image/quality/text-to-image) | $0.05 |
| generate | `grok-imagine-v2` | xai | [xai/grok-imagine-image/v2.0/text-to-image](https://fal.ai/models/xai/grok-imagine-image/v2.0/text-to-image) | $0.06 |
| generate | `ideogram-v4.5` | ideogram | [ideogram/v4.5](https://fal.ai/models/ideogram/v4.5) | $0.06 |
| edit | `nano-banana-2.1-edit` | google | [google/nano-banana-2.1/edit](https://fal.ai/models/google/nano-banana-2.1/edit) | $0.044 |
| edit | `nano-banana-lite-edit` | google | [google/nano-banana-lite/edit](https://fal.ai/models/google/nano-banana-lite/edit) | $0.042 |
| edit | `gpt-image-2.5-flare-edit` | openai | [openai/gpt-image-2.5/flare/edit](https://fal.ai/models/openai/gpt-image-2.5/flare/edit) | $0.05268 |
| edit | `gpt-image-2.5-sunburst-edit` | openai | [openai/gpt-image-2.5/sunburst/edit](https://fal.ai/models/openai/gpt-image-2.5/sunburst/edit) | $0.05268 |
| edit | `gpt-image-2-edit` | openai | [openai/gpt-image-2/edit](https://fal.ai/models/openai/gpt-image-2/edit) | $0.211 |
| edit | `flux-3-edit` | black-forest-labs | [blackforestlabs/flux-3/edit-image](https://fal.ai/models/blackforestlabs/flux-3/edit-image) | $0.048 |
| edit | `flux-3-klein-edit` | black-forest-labs | [blackforestlabs/flux-3/klein/edit-image](https://fal.ai/models/blackforestlabs/flux-3/klein/edit-image) | $0.009 |
| edit | `flux-2-pro-edit` | black-forest-labs | [fal-ai/flux-2-pro/edit](https://fal.ai/models/fal-ai/flux-2-pro/edit) | $0.045 |
| edit | `flux-2-max-edit` | black-forest-labs | [fal-ai/flux-2-max/edit](https://fal.ai/models/fal-ai/flux-2-max/edit) | $0.1 |
| edit | `flux-2-lora-edit` | black-forest-labs | [fal-ai/flux-2/lora/edit](https://fal.ai/models/fal-ai/flux-2/lora/edit) | $0.042 |
| edit | `seedream-5-pro-edit` | bytedance | [bytedance/seedream/v5/pro/edit](https://fal.ai/models/bytedance/seedream/v5/pro/edit) | $0.135 |
| edit | `seedream-5-flash-edit` | bytedance | [bytedance/seedream/v5/flash/edit](https://fal.ai/models/bytedance/seedream/v5/flash/edit) | $0.027 |
| edit | `qwen-image-3-edit` | alibaba | [alibaba/qwen-image-3/edit](https://fal.ai/models/alibaba/qwen-image-3/edit) | $0.04 |
| edit | `grok-imagine-quality-edit` | xai | [xai/grok-imagine-image/quality/edit](https://fal.ai/models/xai/grok-imagine-image/quality/edit) | $0.06 |
| edit | `grok-imagine-v2-edit` | xai | [xai/grok-imagine-image/v2.0/edit](https://fal.ai/models/xai/grok-imagine-image/v2.0/edit) | $0.07 |
| edit | `kling-image` | kuaishou | [fal-ai/kling-image/o3/image-to-image](https://fal.ai/models/fal-ai/kling-image/o3/image-to-image) | $0.028 |
| edit | `ideogram-v4.5-edit` | ideogram | [ideogram/v4.5/edit](https://fal.ai/models/ideogram/v4.5/edit) | $0.06 |

LoRA generation endpoints: `fal-ai/flux-2/lora` ($0.021) and `fal-ai/qwen-image-2512/lora` ($0.035). Training bases remain FLUX.2 and Qwen Image 2512. Flat estimates approximate endpoints whose pricing varies by output size or options.

## Defaults and removals

Defaults are `anthropic/claude-haiku-5.5` for language and vision, `nano-banana-pro` for generation and `nano-banana-2.1-edit` for editing. All 17 language models passed both text and vision; all 17 generation and 17 edit models passed.

Retired selections include direct OpenAI and Anthropic language providers, legacy FLUX Dev and Qwen 2.5 generation, Nano Banana 2, Qwen Image Max Edit and Qwen Image 2 Pro Edit (deprecated), Wan 2.5, face swap, and the older Grok edit endpoint. Historical keys display as raw keys. OpenAI embeddings remain supported.

The three Qwen 3.8 language models were removed because both routes hit the account ZDR guardrail; account policy was not changed. Grok 4.7 was removed because its text route produced no final answer within 4096 tokens on two attempts, although vision passed. Nano Banana 2.1 generation and Nano Banana Pro editing were removed after two benign requests each were rejected by content policy. Nano Banana 2.1 editing and Nano Banana Pro generation passed and remain offered.

The retained fal status research dated 2026-10-30 marks `fal-ai/flux-2-trainer-v2` active and `fal-ai/qwen-image-2512-trainer-v2` deprecated. Both existing training bases are preserved; no training redesign is included.

OpenRouter metadata matched listed vision support, temperature and base rates for offered language models. MiniMax M3.1 Flash metadata reported its $0.075/$0.30 off-peak rates; the catalog deliberately uses the higher $0.15/$0.60 rate for estimates.

## Refresh and release verification

Fetch `https://openrouter.ai/api/v1/models`, check each model’s image input, pricing, and `supported_parameters`, and retrieve `https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=<endpoint>` plus fal pricing and status for each image and trainer endpoint. Compare schemas to catalog parameters and billing seeds. Run one text and one vision request for each language model and one image per generation/edit endpoint, recording sanitized outcomes and reported costs. Remove failures and update this document, migration seed drift tests, and defaults as needed.

**Evidence:** [sanitized paid smoke matrix](model-catalog-live-verification.json), 2026-10-30. The final offered matrix passes; reported image costs were null where fal did not return a cost. FLUX.3 and Kling edits passed a 512px retest after the initial 128px fixture was too small. A fresh PostgreSQL upgrade to 055, downgrade to 054, and re-upgrade to 055 passed against the curated migration on a separate temporary database on the DEV server; Docker was unavailable.

## Operator verification commands

From the repository root, the live script requires network access and real fal credits. It reads `FAL_API_KEY` from the environment or root `.env`, uses the production request builders and writes sanitized results incrementally:

```sh
cd backend
python tests/verify_model_catalog.py --research-only
python tests/verify_model_catalog.py --paid --timeout 300
# After the first process has stopped, retry only failed entries:
python tests/verify_model_catalog.py --paid --skip-research --only-failed --timeout 300
```

For a disposable local PostgreSQL migration cycle, create a dedicated pgvector container and database; never point these commands at an existing database. From the repository root:

```sh
docker run --name cura-catalog-migration-check -e POSTGRES_PASSWORD=catalog-test -e POSTGRES_DB=catalog_test -p 127.0.0.1:55439:5432 -d pgvector/pgvector:pg16
# Wait until: docker exec cura-catalog-migration-check pg_isready -U postgres
cd backend
DATABASE_URL='postgresql://postgres:catalog-test@127.0.0.1:55439/catalog_test' alembic upgrade head
DATABASE_URL='postgresql://postgres:catalog-test@127.0.0.1:55439/catalog_test' alembic downgrade -1
DATABASE_URL='postgresql://postgres:catalog-test@127.0.0.1:55439/catalog_test' alembic upgrade head
DATABASE_URL='postgresql://postgres:catalog-test@127.0.0.1:55439/catalog_test' alembic current
docker rm -f cura-catalog-migration-check
```

After a reviewed deployment and DEV migration, `backend/tests/verify_model_catalog_dev.py --run` requires `DEV_BACKEND_URL`, `DEV_ADMIN_EMAIL`, `DEV_ADMIN_PASSWORD` in the environment; `DEV_IMAGE_ID` and `DEV_CLUSTER_ID` are optional. It modifies the selected image and cluster and incurs charges. Review the sanitized output and separately inspect container logs and Sentry; the script cannot establish absence of all new errors.
