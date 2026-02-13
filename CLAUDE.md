# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Image Model Generator - a full-stack app for AI-powered image tagging, description, clustering, semantic search, LoRA model training, and image generation. Images are processed through a pipeline: ingest → tag → describe → embed → cluster → summarize. Trained LoRA models can be evaluated against source images for quality measurement.

## Deploying Changes

**This project runs via Docker Compose. After finishing any code changes, you MUST rebuild and restart the services so the changes take effect.** Do not wait for the user to ask — do this automatically after every implementation task.

### Steps to apply changes

1. **If frontend files were changed**, verify the build first:
   ```bash
   cd frontend && npm run build
   ```
   Fix any TypeScript errors before proceeding.

2. **Stop all services:**
   ```bash
   docker compose down
   ```

3. **Rebuild images** (use `--no-cache` only when dependencies changed, otherwise omit it for faster builds):
   ```bash
   # Fast rebuild (code changes only)
   docker compose build

   # Full rebuild (dependency changes in requirements.txt or package.json)
   docker compose build --no-cache
   ```

4. **Start services:**
   ```bash
   docker compose up -d
   ```

5. **If there are new database migrations**, run them after containers are healthy:
   ```bash
   docker compose exec backend alembic upgrade head
   ```

6. **Verify services are running:**
   ```bash
   docker compose ps
   docker compose logs backend --tail=10
   docker compose logs celery-worker --tail=5
   ```

7. **Quick smoke test:**
   ```bash
   curl -s http://localhost:8000/api/images/stats | python3 -m json.tool
   curl -s http://localhost:3000 -o /dev/null -w "%{http_code}"
   ```

### When to rebuild what

| What changed | What to rebuild |
|---|---|
| Backend Python code only | `docker compose build backend celery-worker celery-worker-clustering celery-generation` |
| Frontend code only | `docker compose build frontend` |
| Both backend + frontend | `docker compose build` |
| `requirements.txt` or `package.json` | `docker compose build --no-cache` |
| New Alembic migration added | Rebuild backend, then `docker compose exec backend alembic upgrade head` |

### Service URLs

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/api/docs

## Commands (local development, outside Docker)

### Backend (from `backend/`)

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8000
celery -A app.workers.celery_app worker --loglevel=info
celery -A app.workers.celery_app worker -Q clustering --loglevel=info
celery -A app.workers.celery_app worker -Q generation --loglevel=info
alembic upgrade head
alembic downgrade -1
```

### Frontend (from `frontend/`)

```bash
npm install
npm run dev          # Development (http://localhost:3000)
npm run build        # Production build
npm run lint         # ESLint
```

## Architecture

**Stack:** Next.js 14 + FastAPI + PostgreSQL/pgvector + Celery/Redis

**Docker services:** postgres, redis, backend, celery-worker, celery-worker-clustering, celery-generation, celery-beat (optional, profile=scheduled), frontend

**Key patterns:**
- **Provider abstraction** (`backend/app/providers/`): Swappable AI providers (OpenAI/Anthropic/fal.ai) via base classes and factory functions (`get_tagger()`, `get_describer()`, `get_embedder()`, `get_cluster_summarizer()`, `get_trainer()`, `get_generator()`, `get_evaluator()`)
- **Service layer** (`backend/app/services/`): Business logic decoupled from API routes
- **Celery task chaining** (`backend/app/workers/tasks.py`): `process_image_pipeline()` orchestrates tag→describe→embed flow. Upstream changes auto-trigger re-embedding.
- **pgvector**: 1536-dim embeddings for similarity search via cosine distance
- **Hybrid search**: Combines semantic (embedding) and text (tsvector) search with adaptive weighting

**Processing flow:**
1. Upload → `ImageService.ingest_image()` stores file, generates thumbnails (200/400/800px), computes SHA-256 + perceptual hash
2. `tag_image` task → Vision AI extracts flat categorization tags
3. `describe_image` task → Vision AI generates detailed sectioned description for image reproduction
4. `embed_image` task → Creates text embedding from tags + description
5. `cluster_all_images` task → HDBSCAN/KMeans/Graph groups by embedding similarity (with optional UMAP reduction)
6. `summarize_clusters` task → Generates cluster titles and descriptions

**API routes** (`backend/app/api/`):
- `images.py` — Image CRUD, upload (single/batch), reprocess, tag, describe, embed, similar images, file serving
- `folders.py` — Folder CRUD, add/remove images, folder-scoped image listing, folder reprocess
- `clusters.py` — Cluster listing, detail, rename, pin, archive, merge, exclude image, summarize, recluster, export
- `search.py` — Hybrid semantic+text search, tag filtering, tag listing
- `jobs.py` — Job listing/detail/cancel/delete, pipeline triggers (full, tag-all, describe-all, embed-all, reprocess-all, reprocess-failed, reprocess-selected), batch job image listing
- `settings.py` — Prompt presets CRUD, activate preset, prompt get/update/reset/suggest, clustering config get/update/reset, API key management (store/validate/delete), provider config, generation config (per-base-model), training config (per-base-model), base model selection
- `generation.py` — LoRA training (from folders or clusters, with optional per-image captions, multi-base-model: flux-dev/qwen-2.5), image generation, model/image CRUD, model recover/retry, LoRA evaluation (reference + creative pairs with embedding similarity/vision scoring)
- `logs.py` — Pipeline log queries, stats, cleanup

**Database models** (`backend/app/models/`):
- `Image` + `ImageMetadata` (1:1) — Core image data with status tracking, tags, description, embedding, hashes, tsvector
- `Cluster` + `ClusterMembership` — Clustering results with centroid, summary, pin/archive/rename, outlier exclusion
- `Job` — Async job tracking (types: INGEST, TAG, DESCRIBE, EMBED, CLUSTER, SUMMARIZE_CLUSTER, FULL_PIPELINE, REPROCESS, BATCH_REPROCESS, LORA_TRAIN, GENERATE_IMAGE, BATCH_GENERATE, LORA_EVALUATE)
- `Folder` + `FolderImage` — User folders for organizing images (many-to-many)
- `LoraModel` — Trained LoRA adapters linked to folder or cluster source, with training config and status. Supports multiple base models (flux-dev, qwen-2.5)
- `GeneratedImage` — AI-generated images linked to LoRA models with prompt, params, and output files
- `LoraEvaluation` + `EvaluationPair` — Quality evaluation of trained LoRA models. Generates images from source prompts, compares against originals via embedding similarity and vision scoring. Supports "reference" (vs original) and "creative" (novel prompt) pair types
- `PromptPreset` — Named tag+description prompt pairs with active/default flag
- `PipelineLog` — Structured logs (category, level, tokens, duration, provider/model)
- `AppSetting` — Key-value config store
- `APIKey` — Encrypted API key storage with validation status

**Frontend structure** (`frontend/src/`):
- Pages: Home (clusters), Folders, Folder Detail, All Images, Upload, Search, Cluster Detail, Models (with sub-components: TrainModal, FluxTrainForm, QwenTrainForm, SharedTrainFields, ModelSettings, EvaluationDetail), Generate, Jobs, Debug, Settings
- Components: Header (search+stats), Sidebar (navigation), ImageCard, ImageDrawer (detail slide-over), ImageGrid (paginated with filters+batch actions), ClusterCard, FolderCard, GeneratedImageCard, AddToFolderDialog, PipelineProgress
- API client: `lib/api.ts` — Typed Axios functions for all endpoints
- State: TanStack Query with polling (5s jobs, 3s logs, 10s stats)

**Alembic migrations:** 16 versions (001-016) covering initial schema through LoRA evaluations and pair types

## Environment

Requires `.env` in project root with:
- `OPENAI_API_KEY` (required for embeddings; also used for vision if chosen)
- `ANTHROPIC_API_KEY` (optional, for vision/summarization)
- `FAL_API_KEY` (optional, for LoRA training and image generation via fal.ai)
- `DEFAULT_VISION_PROVIDER` (openai/anthropic)
- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`
