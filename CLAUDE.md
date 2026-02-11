# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Image Model Generator - a full-stack app for AI-powered image tagging, description, clustering, and semantic search. Images are processed through a pipeline: ingest → tag → describe → embed → cluster → summarize.

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
| Backend Python code only | `docker compose build backend celery-worker celery-worker-clustering` |
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

**Key patterns:**
- **Provider abstraction** (`backend/app/providers/`): Swappable AI providers (OpenAI/Anthropic) via base classes and factory functions (`get_tagger()`, `get_describer()`, etc.)
- **Service layer** (`backend/app/services/`): Business logic decoupled from API routes
- **Celery task chaining** (`backend/app/workers/tasks.py`): `process_image_pipeline()` orchestrates tag→describe→embed flow
- **pgvector**: 1536-dim embeddings for similarity search via cosine distance

**Processing flow:**
1. Upload → `ImageService.ingest_image()` stores file, generates thumbnails
2. `tag_image` task → Vision AI extracts flat categorization tags
3. `describe_image` task → Vision AI generates detailed sectioned description for image reproduction
4. `embed_image` task → Creates text embedding from tags + description
5. `cluster_all_images` task → HDBSCAN groups by embedding similarity
6. `summarize_clusters` task → Generates cluster descriptions

**API structure:**
- Routes in `backend/app/api/` (images, clusters, search, jobs, settings)
- Schemas in `backend/app/schemas/` (Pydantic request/response models)
- Frontend API client in `frontend/src/lib/api.ts` (typed Axios functions)

**Database models** (`backend/app/models/`):
- `Image` + `ImageMetadata` (1:1) - core image data with embeddings
- `Cluster` + `ClusterMembership` - groupings with centroids
- `Job` - async job tracking
- `AppSetting` - key/value settings (guidance defaults)

## Environment

Requires `.env` in project root with:
- `OPENAI_API_KEY` (required)
- `ANTHROPIC_API_KEY` (optional)
- `DEFAULT_VISION_PROVIDER` (openai/anthropic)
- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`
