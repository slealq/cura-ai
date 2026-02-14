# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Image Model Generator - a multi-user full-stack app for AI-powered image tagging, description, clustering, semantic search, LoRA model training, and image generation. Images are processed through a pipeline: ingest → tag → describe → embed → cluster → summarize. Trained LoRA models can be evaluated against source images for quality measurement. All data is isolated per user via `user_id` foreign keys on every table.

## Environments

Four environments exist, each with a UI badge in the sidebar (except PROD):

| Environment | Frontend | Backend | UI Badge | How to run |
|---|---|---|---|---|
| **Local** | Docker (localhost:3000) | Docker (localhost:8000) | Blue "Local" | `docker compose up -d` |
| **Local w/DEV Backend** | Local dev (localhost:3001) | Azure DEV cloud | Amber "Local w/DEV Backend" | `cd frontend && npm run dev:cloud` |
| **DEV** | Azure Static Web App | Azure Container Apps | Amber "DEV" | Merge PR to `dev` branch (CI/CD) |
| **PROD** | Azure Static Web App | Azure Container Apps | None | Manual dispatch (CI/CD) |

The badge is controlled by `NEXT_PUBLIC_ENV_LABEL` env var (`local`, `dev-backend`, `dev`, `prod`).

### Service URLs

| Environment | Frontend | Backend API | API Docs |
|---|---|---|---|
| Local | http://localhost:3000 | http://localhost:8000 | http://localhost:8000/api/docs |
| Local w/DEV Backend | http://localhost:3001 | https://cae-imggen-dev-backend.ambitioussand-1e60af3e.eastus.azurecontainerapps.io | Same + `/api/docs` |
| DEV | https://victorious-mushroom-01a2cc60f.4.azurestaticapps.net | Same as above | Same + `/api/docs` |
| PROD | Not yet provisioned | Not yet provisioned | — |

---

## Git Workflow & Branch Protection

**Protected branches:** `master` and `dev` — no direct pushes allowed.

**Branch naming:** All work happens on personal branches: `u/<username>/<feature-name>` (e.g., `u/slealq/add-dark-mode`).

**Flow:**
1. Create a personal branch from `dev`: `git checkout -b u/slealq/my-feature dev`
2. Push to the personal branch: `git push -u origin u/slealq/my-feature`
3. Create a PR to `dev` on GitHub (requires approval)
4. After merging to `dev`, CI/CD deploys to the DEV environment
5. Promote `dev` → `master` via GitHub Actions: **Actions → "Promote to PROD" → Run workflow**

**Enforcement:**
- Pre-push Git hook (`.githooks/pre-push`) blocks direct pushes to `master` and `dev`. New clones must run `./scripts/setup-hooks.sh` to activate hooks.
- CI guard job blocks PRs targeting `master` — only the promote workflow can update `master`.
- Branches are auto-deleted after PR merge.

**When committing changes via Claude Code:** Always commit to the current personal branch. Never push directly to `master` or `dev`.

---

## Deploying Changes

### Local (Docker Compose)

**This project runs via Docker Compose locally. After finishing any code changes, you MUST rebuild and restart the services so the changes take effect.** Do not wait for the user to ask — do this automatically after every implementation task.

#### Steps to apply changes

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

7. **Quick smoke test** (all API endpoints except `/auth/login` and `/auth/register` require a Bearer token):
   ```bash
   # Get a token
   TOKEN=$(curl -s http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
     -d '{"email":"stuart.leal23@gmail.com","password":"password"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

   curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/images/stats | python3 -m json.tool
   curl -s http://localhost:3000 -o /dev/null -w "%{http_code}"
   ```

#### When to rebuild what

| What changed | What to rebuild |
|---|---|
| Backend Python code only | `docker compose build backend celery-worker celery-worker-clustering celery-worker-generation` |
| Frontend code only | `docker compose build frontend` |
| Both backend + frontend | `docker compose build` |
| `requirements.txt` or `package.json` | `docker compose build --no-cache` |
| New Alembic migration added | Rebuild backend, then `docker compose exec backend alembic upgrade head` |

#### Running Local w/DEV Backend

Run the frontend locally against the Azure DEV backend on port 3001 (can run simultaneously with the Docker frontend on 3000):

```bash
cd frontend && npm run dev:cloud
```

This injects `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ENV_LABEL=dev-backend` inline — no `.env.local` changes needed.

### Deploying to DEV (Azure)

#### Automated (CI/CD) — recommended

Push to the `dev` branch. The `deploy-dev.yml` workflow will:
1. Build backend Docker image and push to ACR (tagged `:dev`)
2. Build frontend with DEV backend URL, deploy to Azure Static Web App
3. Update all 4 Container Apps with the new image

**Note:** Alembic migrations are NOT auto-run by CI (`az containerapp exec` requires a TTY). Run migrations manually when needed:
```bash
az containerapp exec --name cae-imggen-dev-backend --resource-group rg-imggen-dev --command "alembic upgrade head"
```

**Required GitHub Secrets:** `ACR_LOGIN_SERVER`, `ACR_USERNAME`, `ACR_PASSWORD`, `DEV_BACKEND_URL`, `DEV_SWA_TOKEN`, `DEV_RESOURCE_GROUP`, `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`

#### Manual (from local machine)

```bash
# 1. Build for linux/amd64 (required — Apple Silicon builds arm64 by default)
docker build --platform linux/amd64 -t acrimggen.azurecr.io/imggen-backend:latest backend/

# 2. Push to Azure Container Registry
az acr login --name acrimggen
docker push acrimggen.azurecr.io/imggen-backend:latest

# 3. Update all 4 Container Apps
az containerapp update --name cae-imggen-dev-backend --resource-group rg-imggen-dev --image acrimggen.azurecr.io/imggen-backend:latest
az containerapp update --name cae-imggen-dev-celery-worker --resource-group rg-imggen-dev --image acrimggen.azurecr.io/imggen-backend:latest
az containerapp update --name cae-imggen-dev-celery-clustering --resource-group rg-imggen-dev --image acrimggen.azurecr.io/imggen-backend:latest
az containerapp update --name cae-imggen-dev-celery-generation --resource-group rg-imggen-dev --image acrimggen.azurecr.io/imggen-backend:latest

# 4. Run migrations (add firewall rule for your IP first)
MY_IP=$(curl -s ifconfig.me)
az postgres flexible-server firewall-rule create --resource-group rg-imggen-dev --name psql-imggen-dev2 --rule-name AllowLocalDev --start-ip-address "$MY_IP" --end-ip-address "$MY_IP"
docker run --rm -e DATABASE_URL="postgresql://imggenadmin:<password>@psql-imggen-dev2.postgres.database.azure.com:5432/imggen?sslmode=require" acrimggen.azurecr.io/imggen-backend:latest alembic upgrade head
```

### DEV Environment Management (Start/Stop/Status)

The DEV environment costs ~$50-80/month when running. Stop it when not in use:

```bash
# Check current status of all resources
./scripts/dev-env-status.sh

# Stop everything (saves ~$50-80/month)
./scripts/dev-env-stop.sh

# Start everything back up
./scripts/dev-env-start.sh
```

| Script | What it does |
|---|---|
| `dev-env-status.sh` | Shows state of PostgreSQL, Redis, and all 4 Container Apps (replica counts, min/max) |
| `dev-env-stop.sh` | Scales Container Apps to 0/0, stops PostgreSQL, deletes Redis (Basic SKU has no stop). Saves Redis key to `.redis-key-dev` |
| `dev-env-start.sh` | Starts PostgreSQL (~1-2 min), recreates Redis Basic C0 (~5-10 min), updates Container App secrets with new Redis connection, scales apps back (backend 1/3, workers 1/2 or 1/1), polls for backend health, adds DB firewall rule for current IP |

### Deploying to PROD (Azure)

**Status: PROD is fully scaffolded but NOT yet provisioned.**

Terraform config exists at `infra/environments/prod/` with production-grade settings (higher SKUs, more replicas, geo-redundant backup, purge-protected Key Vault). The `deploy-prod.yml` CI/CD workflow is ready (manual dispatch, re-tags DEV image as PROD).

#### What exists

- **Terraform IaC** (`infra/environments/prod/`): Resource group `rg-imggen-prod`, PostgreSQL `psql-imggen-prod` (B_Standard_B2s, 65GB, geo-redundant), Redis `redis-imggen-prod` (Standard tier), Container Apps with higher scaling (backend 2-5 replicas, workers 2-4), Static Web App (Standard tier), Key Vault with purge protection
- **CI/CD** (`.github/workflows/deploy-prod.yml`): Manual dispatch → re-tags `imggen-backend:dev` as `:prod` in ACR → deploys frontend to PROD SWA → updates PROD Container Apps. Migrations must be run manually.
- **Frontend env** (`frontend/.env.prod`): `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_ENV_LABEL=prod`

#### Before provisioning PROD

1. **Set Terraform variables**: `db_admin_user`, `db_admin_password`, `jwt_secret_key`, API keys (OpenAI, Anthropic, fal.ai)
2. **Configure GitHub Secrets**: `PROD_BACKEND_URL`, `PROD_SWA_TOKEN`, `PROD_RESOURCE_GROUP` (plus the shared OIDC/ACR secrets already used by DEV)
3. **Run Terraform**: `cd infra/environments/prod && terraform init && terraform apply`
4. **Update `frontend/.env.prod`**: Set correct `NEXT_PUBLIC_API_URL` with the actual Container App hostname from Terraform output
5. **Run initial migration**: `alembic upgrade head` against the new PROD database
6. **Deploy**: Trigger `deploy-prod.yml` workflow manually from GitHub Actions

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

**Local Docker services:** postgres, redis, backend, celery-worker, celery-worker-clustering, celery-worker-generation, celery-beat (optional, profile=scheduled), frontend

**Azure Cloud services (per environment):**

| Component | Azure Service | DEV Resource Name |
|-----------|--------------|-------------------|
| Image/file storage | Azure Blob Storage | `stimggendev` (container: `images`) |
| Backend API + Celery workers | Azure Container Apps | `cae-imggen-dev-backend`, `cae-imggen-dev-celery-*` |
| Docker images | Azure Container Registry (shared) | `acrimggen.azurecr.io` |
| Database | Azure PostgreSQL Flexible Server (pgvector) | `psql-imggen-dev2` (eastus2) |
| Message broker + cache | Azure Cache for Redis | `redis-imggen-dev` |
| Frontend | Azure Static Web Apps | `swa-imggen-dev` (eastus2) |
| Secrets | Azure Key Vault | `kv-imggen-dev` |
| Infrastructure-as-code | Terraform (remote state in Azure Storage) | `stimggentfstate` / `tfstate` container |

**Storage abstraction** (`backend/app/services/storage.py`): Supports `local` and `azure` backends via `STORAGE_BACKEND` config. Azure mode uses Blob Storage with SAS URL redirects for file serving (302 redirect instead of streaming bytes). Configured via `AZURE_STORAGE_CONNECTION_STRING` and `AZURE_STORAGE_CONTAINER`.

**Key patterns:**
- **Multi-user auth** (`backend/app/core/security.py`): JWT-based authentication (access tokens 30min, refresh tokens 7 days) using bcrypt + python-jose. Every API endpoint (except `/auth/login` and `/auth/register`) requires `get_current_user` dependency. File-serving endpoints use `get_current_user_from_token_param` (accepts `?token=` query param for `<img src>` usage). Admin-only endpoints use `require_admin`.
- **User data isolation**: All services accept `user_id` in their constructor (e.g., `get_image_service(db, user_id)`). All queries filter by `user_id`. Celery tasks receive `user_id` as an explicit parameter.
- **Provider abstraction** (`backend/app/providers/`): Swappable AI providers (OpenAI/Anthropic/fal.ai) via base classes and factory functions (`get_tagger()`, `get_describer()`, `get_embedder()`, `get_cluster_summarizer()`, `get_trainer()`, `get_generator()`, `get_evaluator()`)
- **Service layer** (`backend/app/services/`): Business logic decoupled from API routes. Each service takes `(db, user_id)` and filters all queries by user.
- **Celery task chaining** (`backend/app/workers/tasks.py`): `process_image_pipeline()` orchestrates tag→describe→embed flow. Upstream changes auto-trigger re-embedding. All tasks accept `user_id` parameter.
- **pgvector**: 1536-dim embeddings for similarity search via cosine distance
- **Hybrid search**: Combines semantic (embedding) and text (tsvector) search with adaptive weighting

**Processing flow:**
1. Upload → `ImageService.ingest_image()` stores file, generates thumbnails (200/400/800px), computes SHA-256 + perceptual hash
2. `tag_image` task → Vision AI extracts flat categorization tags
3. `describe_image` task → Vision AI generates detailed sectioned description for image reproduction
4. `embed_image` task → Creates text embedding from tags + description
5. `cluster_all_images` task → HDBSCAN/KMeans/Graph groups by embedding similarity (with optional UMAP reduction)
6. `summarize_clusters` task → Generates cluster titles and descriptions

**API routes** (`backend/app/api/`): All endpoints require Bearer token auth (`get_current_user` dependency) unless noted.
- `auth.py` — Login, register (public, no auth), refresh token, get current user, create user (admin-only), list users (admin-only), toggle sync (admin-only)
- `images.py` — Image CRUD, upload (single/batch), reprocess, tag, describe, embed, similar images, file serving (token via query param)
- `folders.py` — Folder CRUD, add/remove images, folder-scoped image listing, folder reprocess
- `clusters.py` — Cluster listing, detail, rename, pin, archive, merge, exclude image, summarize, recluster, export
- `search.py` — Hybrid semantic+text search, tag filtering, tag listing
- `jobs.py` — Job listing/detail/cancel/delete, pipeline triggers (full, tag-all, describe-all, embed-all, reprocess-all, reprocess-failed, reprocess-selected), batch job image listing
- `settings.py` — Prompt presets CRUD, activate preset, prompt get/update/reset/suggest, clustering config get/update/reset, API key management (store/validate/delete, env var keys visible to admin only), provider config, generation config (per-base-model), training config (per-base-model), base model selection
- `generation.py` — LoRA training (from folders or clusters, with optional per-image captions, multi-base-model: flux-dev/qwen-2.5), image generation, model/image CRUD, model recover/retry, LoRA evaluation (reference + creative pairs with embedding similarity/vision scoring), file serving (token via query param)
- `logs.py` — Pipeline log queries, stats (filtered by user), cleanup (admin-only)

**Database models** (`backend/app/models/`): All data models have a `user_id` foreign key to the `users` table (NOT NULL with CASCADE delete, except `PipelineLog` which is nullable). Composite unique constraints replace simple uniques where needed (e.g., `user_id + file_hash` on images).
- `User` — Authentication and data ownership. Fields: email (unique), hashed_password, display_name, role (admin/user), is_active, is_verified, sync_enabled, timestamps. Seed admin: stuart.leal23@gmail.com
- `Image` + `ImageMetadata` (1:1) — Core image data with status tracking, tags, description, embedding, hashes, tsvector
- `Cluster` + `ClusterMembership` — Clustering results with centroid, summary, pin/archive/rename, outlier exclusion
- `Job` — Async job tracking (types: INGEST, NORMALIZE, TAG, DESCRIBE, EMBED, CLUSTER, SUMMARIZE_CLUSTER, FULL_PIPELINE, REPROCESS, BATCH_REPROCESS, LORA_TRAIN, GENERATE_IMAGE, BATCH_GENERATE, LORA_EVALUATE)
- `Folder` + `FolderImage` — User folders for organizing images (many-to-many)
- `LoraModel` — Trained LoRA adapters linked to folder or cluster source, with training config and status. Supports multiple base models (flux-dev, qwen-2.5)
- `GeneratedImage` — AI-generated images linked to LoRA models with prompt, params, and output files
- `LoraEvaluation` + `EvaluationPair` — Quality evaluation of trained LoRA models. Generates images from source prompts, compares against originals via embedding similarity and vision scoring. Supports "reference" (vs original) and "creative" (novel prompt) pair types
- `PromptPreset` — Named tag+description prompt pairs with active/default flag
- `PipelineLog` — Structured logs (category, level, tokens, duration, provider/model). user_id is nullable (system-level logs)
- `AppSetting` — Key-value config store
- `APIKey` — Encrypted API key storage with validation status

**Frontend structure** (`frontend/src/`):
- Pages: Login (sign-in/sign-up toggle), Home (clusters), Folders, Folder Detail, All Images, Upload, Search, Cluster Detail, Models (with sub-components: TrainModal, FluxTrainForm, QwenTrainForm, SharedTrainFields, ModelSettings, EvaluationDetail), Model Evaluate, Evaluation Detail, Generate, Jobs, Debug, Settings
- Auth: `contexts/AuthContext.tsx` provides `login`, `register`, `logout`, `user`, `isAuthenticated`. `AuthGate` in layout redirects unauthenticated users to `/login`. Axios interceptors attach Bearer token to all requests and handle 401 with automatic token refresh.
- Theme: `contexts/ThemeContext.tsx` provides light/dark/auto theme switching with timezone-aware auto mode (dark 19:00-07:00). Persisted in localStorage.
- Components: Header (search+stats), Sidebar (navigation + user menu with logout), ImageCard, ImageDrawer (detail slide-over), ImageGrid (paginated with filters+batch actions), ClusterCard, FolderCard, GeneratedImageCard, AddToFolderDialog, PipelineProgress
- API client: `lib/api.ts` — Typed Axios functions for all endpoints. `authUrl()` helper appends `?token=` to image/thumbnail URLs for authenticated file serving via `<img src>`. Supports cross-origin API calls via `NEXT_PUBLIC_API_URL` env var (used when frontend runs locally against cloud backend).
- State: TanStack Query with polling (5s jobs, 3s logs, 10s stats)

**Alembic migrations:** 18 versions (001-018) covering initial schema through multi-user support. Migration 017 creates the `users` table, seeds the admin user, adds `user_id` to all 11 data tables with backfill, and converts simple unique constraints to composite (user_id + field). Migration 018 adds `sync_enabled` to users for data sync.

## Authentication

- **JWT-based**: Access tokens (30min) + refresh tokens (7 days), HS256 algorithm
- **Password hashing**: bcrypt (direct, not passlib)
- **Seed admin**: stuart.leal23@gmail.com / password (created in migration 017)
- **Public endpoints**: `POST /auth/login`, `POST /auth/register` (no auth required)
- **Sign-up**: Open registration via `/auth/register`. New users get the `user` role. Only admins can create other admins via `POST /auth/users`.
- **File serving**: Thumbnail/image endpoints accept token via `?token=` query parameter (required for `<img src>` tags which can't send Authorization headers)
- **API key isolation**: Each user manages their own API keys. Server-level env var keys are only visible to admin users.

## Environment

### Local (`.env` in project root)
- `OPENAI_API_KEY` (required for embeddings; also used for vision if chosen — visible as fallback to admin only)
- `ANTHROPIC_API_KEY` (optional, for vision/summarization — visible as fallback to admin only)
- `FAL_API_KEY` (optional, for LoRA training and image generation via fal.ai — visible as fallback to admin only)
- `DEFAULT_VISION_PROVIDER` (openai/anthropic)
- `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`
- `JWT_SECRET_KEY` (defaults to `change-me-in-production-jwt-secret` — **must override in production**)

### Azure Cloud (set via Container App secrets in Terraform)
All the above, plus:
- `STORAGE_BACKEND` — `azure` (enables Azure Blob Storage; `local` for Docker Compose)
- `AZURE_STORAGE_CONNECTION_STRING` — Azure Storage account connection string
- `AZURE_STORAGE_CONTAINER` — Blob container name (default: `images`)
- `ENVIRONMENT` — `local`, `dev`, or `prod`
- `CORS_ORIGINS` — Comma-separated allowed origins (configurable in `backend/app/main.py`)

### Frontend environment files
- `frontend/.env.dev` — Points `NEXT_PUBLIC_API_URL` to DEV cloud backend
- `frontend/.env.prod` — Points `NEXT_PUBLIC_API_URL` to PROD cloud backend
- Copy to `.env.local` for local dev against cloud: `cp .env.dev .env.local`

## Infrastructure

**Terraform** (`infra/`): Modular Terraform configuration for Azure resources.
- `infra/modules/` — Reusable modules: resource_group, storage, database, redis, container_registry, container_apps, static_web_app, key_vault
- `infra/environments/dev/` — DEV environment config (eastus, PostgreSQL in eastus2). **Provisioned and active.**
- `infra/environments/prod/` — PROD environment config. **Fully scaffolded, NOT yet provisioned.** See "Deploying to PROD" section for prerequisites.
- `infra/shared/` — Shared resources (ACR: `acrimggen.azurecr.io`)
- State stored in Azure Storage: `stimggentfstate` account, `tfstate` container

**CI/CD** (`.github/workflows/`):
- `ci.yml` — PR validation: backend lint (ruff) + frontend lint & build. Guard job blocks PRs targeting `master`.
- `deploy-dev.yml` — Push to `dev` branch → build → push to ACR (`:dev` tag) → deploy frontend to SWA → update 4 Container Apps. Migrations are manual.
- `deploy-prod.yml` — Manual dispatch → re-tag `:dev` as `:prod` in ACR → deploy frontend to PROD SWA → update PROD Container Apps. Migrations are manual.
- `promote-to-prod.yml` — Manual dispatch → fast-forwards `master` to match `dev` (verifies ancestor relationship first).
- `terraform.yml` — Plan on PR, apply on merge for `infra/**` changes. **Known issue:** Workflow targets `main` branch (not `master`) and uses `infra/$env` paths instead of `infra/environments/$env` — currently non-functional. Terraform is run manually from local machine.

**Migration script** (`scripts/migrate_storage.py`): Migrates local filesystem images to Azure Blob Storage with concurrent uploads and incremental skip support.

## Data Sync (Local ↔ Cloud)

Bidirectional sync of database records and files between local and cloud for admin-selected users.

### Enable sync for a user (admin only)

```bash
TOKEN=$(curl -s http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"stuart.leal23@gmail.com","password":"password"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Toggle sync on for user ID 1
curl -X PATCH http://localhost:8000/api/auth/users/1/sync \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"sync_enabled": true}'

# List all users with sync status
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auth/users
```

### Run sync

```bash
# Dry run (see what would happen)
python scripts/sync_data.py \
  --direction local-to-cloud \
  --local-db "postgresql://postgres:postgres@localhost:5432/design_pipeline" \
  --cloud-db "postgresql://imggenadmin:PASS@psql-imggen-dev2.postgres.database.azure.com:5432/imggen?sslmode=require" \
  --azure-connection-string "DefaultEndpointsProtocol=https;..." \
  --dry-run

# Full sync (DB + files)
python scripts/sync_data.py \
  --direction local-to-cloud \
  --local-db "postgresql://postgres:postgres@localhost:5432/design_pipeline" \
  --cloud-db "postgresql://imggenadmin:PASS@psql-imggen-dev2.postgres.database.azure.com:5432/imggen?sslmode=require" \
  --azure-connection-string "DefaultEndpointsProtocol=https;..." \
  --local-storage ./storage

# Reverse direction
python scripts/sync_data.py --direction cloud-to-local ...

# DB only (skip file transfer)
python scripts/sync_data.py --direction cloud-to-local ... --skip-files

# Files only (skip DB)
python scripts/sync_data.py --direction local-to-cloud ... --skip-db
```

### What gets synced

All data tables for sync-enabled users in FK dependency order: users → images → image_metadata → folders → folder_images → clusters → cluster_memberships → jobs → lora_models → generated_images → lora_evaluations → evaluation_pairs → prompt_presets → app_settings.

**Excluded:** `api_keys` (encrypted per-environment, not portable), `pipeline_logs` (large, low value), `hashed_password` (users table — passwords are environment-specific).

**ID mapping:** Records matched by natural keys (see table below). Foreign keys remapped via old→new ID maps built incrementally. Upsert: existing records updated, new ones inserted. Each row uses a database SAVEPOINT so a single row failure doesn't abort the transaction.

| Table | Natural Key |
|---|---|
| users | email |
| images | object_key |
| image_metadata | image_id |
| folders | user_id, name |
| folder_images | folder_id, image_id |
| clusters | user_id, run_id, created_at |
| cluster_memberships | cluster_id, image_id |
| jobs | user_id, created_at, job_type |
| lora_models | user_id, name |
| generated_images | object_key (fallback: user_id, created_at, prompt) |
| lora_evaluations | user_id, created_at |
| evaluation_pairs | generated_object_key |
| prompt_presets | user_id, name |
| app_settings | user_id, key |

**Natural key design rules:** Natural keys must uniquely identify each row. Avoid using FK columns (like `lora_model_id`) in natural keys — FK IDs differ between source and destination, breaking the remap lookup. Use stable non-FK columns instead (e.g., `user_id` + `created_at`). Also avoid keys where multiple rows can share the same values (e.g., all clusters in a run share the same `run_id`).

**Thumbnail URI translation:** Paths automatically converted between formats:
- Local: `/app/storage/thumbnails/abc123_200.jpg`
- Azure: `azure://images/thumbnails/abc123_200.jpg`

**File sync:** Original images, thumbnails, generated images, and generated thumbnails uploaded/downloaded concurrently (10 workers). Skips files that already exist at destination. File paths are derived from `object_key` values in the `images` and `generated_images` tables.

**Performance note:** The DB sync performs individual upserts per row over the network (~5ms/row to Azure). A full sync of ~6000 rows takes ~30 minutes. Use `--skip-files` or `--skip-db` to sync only what's needed. For bulk file uploads without DB sync, `az storage blob upload-batch` is much faster.
