# Design Idea Ingestion Pipeline

Automatically ingest, tag, cluster, and browse design inspiration images using AI. Images flow through a processing pipeline that extracts tags, generates descriptions, creates embeddings for semantic search, and clusters similar images together.

## Features

### Image Processing Pipeline
- **Auto-tagging**: Extract flat categorization tags using vision AI (GPT-4o or Claude Sonnet)
- **Auto-descriptions**: Generate detailed sectioned descriptions optimized for image reproduction
- **Embedding generation**: Create 1536-dim text embeddings from tags + descriptions for semantic similarity
- **Automatic chaining**: Upstream changes (re-tagging or re-describing) automatically trigger re-embedding

### Clustering
- **Multiple algorithms**: HDBSCAN (default), K-Means (auto-K), or Graph-based (Louvain community detection)
- **UMAP dimensionality reduction**: Optional preprocessing before clustering with configurable parameters
- **AI cluster summaries**: Auto-generated titles and descriptions for each cluster
- **Cluster management**: Pin, archive, rename, merge clusters; exclude individual images from clusters
- **Export**: Download cluster data as JSON or ZIP

### Search & Discovery
- **Hybrid search**: Combines semantic (embedding) and text (tsvector full-text) search with adaptive weighting — short queries favor text match, longer queries favor semantic similarity
- **Tag filtering**: Filter images by specific tags
- **Similar images**: Find visually similar images using embedding cosine distance

### Folder Organization
- **Folder management**: Create, rename, delete folders with descriptions
- **Image assignment**: Add/remove images to/from multiple folders
- **Folder-scoped actions**: View, filter, and batch-reprocess images within a folder
- **Preview thumbnails**: Folder cards show up to 4 preview images

### Prompt System
- **Prompt presets**: Named pairs of tag + description prompts for different use cases
- **Active preset**: One preset is active at a time and used as the default for pipeline processing
- **Per-image overrides**: Override prompts when reprocessing individual images
- **AI prompt suggestions**: Describe what you want changed and get AI-suggested prompt modifications
- **Factory reset**: Reset prompts to built-in defaults at any time

### Batch Operations
- **Full pipeline**: Process all pending images through tag → describe → embed
- **Step-by-step**: Run tag-all, describe-all, or embed-all independently
- **Batch reprocess**: Reprocess all images, only failed images, or a selected subset
- **Folder reprocess**: Reprocess all images in a specific folder
- **Job monitoring**: Track progress of all async jobs with real-time polling

### Observability
- **Pipeline logs**: Structured logging for every API call, task execution, and pipeline event
- **Token tracking**: Input/output token counts for all AI API calls
- **Duration tracking**: Timing for all AI operations
- **Log filtering**: Filter by category (API Call, Task, Pipeline, System), level, image, job, or text search
- **Auto-cleanup**: Daily scheduled cleanup of logs older than 7 days

### Provider Abstraction
- **Swappable vision providers**: OpenAI (GPT-4o) or Anthropic (Claude Sonnet) for tagging and describing
- **Swappable summarizers**: OpenAI or Anthropic for cluster summaries
- **Embeddings**: OpenAI text-embedding-3-small (1536 dimensions)
- **Factory functions**: `get_tagger()`, `get_describer()`, `get_embedder()`, `get_cluster_summarizer()`

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Next.js 14    │────▶│    FastAPI      │────▶│  PostgreSQL 16  │
│   (Frontend)    │     │    (Backend)    │     │   + pgvector    │
│   port 3000     │     │    port 8000    │     │   port 5432     │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                        ┌────────▼────────┐     ┌─────────────────┐
                        │  Celery Workers │────▶│   Redis 7       │
                        │  (Processing)   │     │   port 6379     │
                        └────────┬────────┘     └─────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │  Tagger  │ │Describer │ │ Embedder │
              │ (GPT-4o/ │ │ (GPT-4o/ │ │ (OpenAI) │
              │  Claude) │ │  Claude) │ │          │
              └──────────┘ └──────────┘ └──────────┘
```

### Docker Services

| Service | Container | Purpose |
|---------|-----------|---------|
| `postgres` | pgvector/pgvector:0.7.0-pg16 | Database with vector extension |
| `redis` | redis:7-alpine | Celery broker (db1) and result backend (db2) |
| `backend` | FastAPI + uvicorn | REST API server |
| `celery-worker` | Celery (concurrency=1) | Processes tag/describe/embed tasks (rate-limited) |
| `celery-worker-clustering` | Celery (concurrency=2, queue=clustering) | Clustering, batch reprocess, summarization |
| `celery-beat` | Celery Beat (optional, profile=scheduled) | Scheduled tasks (log cleanup) |
| `frontend` | Next.js standalone | Web UI |

### Processing Pipeline

```
Upload ─▶ Ingest ─▶ Tag ─▶ Describe ─▶ Embed ─▶ Cluster ─▶ Summarize
              │        │        │          │         │           │
              ▼        ▼        ▼          ▼         ▼           ▼
           Store    Vision    Vision    Embedding  HDBSCAN/    GPT-4o
           + hash    AI        AI      (1536-dim)  KMeans/    summary
           + thumb                                  Graph
```

1. **Ingest**: Store image file, generate 3 thumbnail sizes (200/400/800px), compute SHA-256 hash (deduplication) and perceptual hash, extract dimensions and MIME type
2. **Tag**: Vision AI extracts a flat list of categorization tags (style, subject, mood, etc.)
3. **Describe**: Vision AI generates a detailed sectioned description designed for image reproduction
4. **Embed**: Concatenates tags + description text, generates 1536-dim OpenAI embedding
5. **Cluster**: Groups embedded images using configured algorithm (HDBSCAN default) with optional UMAP reduction
6. **Summarize**: AI generates a title and bullet-point description for each cluster from common tags and sample descriptions

## Quick Start

### Prerequisites

- Docker & Docker Compose
- OpenAI API key (required for embeddings; also used for vision if chosen)
- Anthropic API key (optional, for vision/summarization)

### 1. Clone and configure

```bash
# Create .env file with API keys
cat > .env << EOF
OPENAI_API_KEY=sk-your-key-here
ANTHROPIC_API_KEY=sk-ant-your-key-here  # optional
EOF
```

### 2. Start services

```bash
docker compose up -d
```

### 3. Access the UI

Open http://localhost:3000

### 4. Upload images

- **Upload page**: Drag & drop or select files (PNG, JPG, JPEG, GIF, WebP, BMP). Optionally assign to a folder.
- **Watch folder**: Drop images in `./watch_folder/` for auto-ingestion
- **API**: `POST /api/images/upload` or `POST /api/images/upload/batch`

### 5. Process images

Images are automatically queued for processing after upload. Monitor progress on the Jobs page or trigger steps manually.

## Web UI Pages

### Clusters (Home) — `/`
Dashboard showing all image clusters. Pinned clusters appear at the top. Each cluster card displays a thumbnail grid, title, image count, summary, and common tags.

### Folders — `/images`
Browse and create folders for organizing images. Folder cards show preview thumbnails and image counts. "All Images" link shows every image in the library.

### Folder Detail — `/images/folder/[id]`
View images within a folder. Inline-edit folder name/description. Batch-select images to remove from folder or reprocess. Delete folder (images are preserved).

### All Images — `/images/all`
Grid view of all images with status filters (Ingested, Tagged, Described, Embedded, Clustered, Failed). Select images to batch-reprocess or add to folders.

### Upload — `/upload`
Drag-and-drop upload with file preview grid. Select or create a folder inline before uploading.

### Search — `/search`
Semantic search by natural language query. Results show similarity score badges. Adaptive hybrid search combines embedding similarity with full-text matching.

### Cluster Detail — `/clusters/[id]`
View cluster images, AI summary, and common tags. Actions: rename, pin/unpin, archive, export (JSON/ZIP), regenerate summary.

### Jobs — `/jobs`
Real-time job monitor (5s polling) with pipeline statistics. Trigger individual steps (Tag All, Describe All, Embed All), batch operations (Reprocess All, Reprocess Failed), or clustering (Recluster, Summarize All). Progress bars for batch jobs. Cancel running jobs.

### Debug — `/debug`
Structured pipeline logs with filtering by category, level, and text search. Expandable log rows show full detail: token counts, duration, prompts used, model responses, and error messages. Log statistics dashboard.

### Settings — `/settings`
Three sections:
- **Pipeline Stats**: Image and cluster counts with status breakdown
- **Prompt Library**: CRUD for named prompt presets (tag + description prompts). Activate a preset as default. AI-powered prompt suggestion tool. Factory reset.
- **Clustering Settings**: Algorithm selection (HDBSCAN/K-Means/Graph), UMAP toggle with parameters, algorithm-specific tuning sliders, quick tips. Save, reset, or recluster directly.

### Image Drawer (Slide-over)
Click any image to open a detail drawer showing: full image, pipeline progress indicator, tags, description, metadata (dimensions, file size, source), processing info (models used), similar images, folders. Action buttons: Tag, Describe, Embed, Reprocess (each with optional prompt override and preset selector). Live polling during processing with toast notifications on completion.

## API Endpoints

Full interactive docs available at http://localhost:8000/api/docs

### Images (`/api/images`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/upload` | Upload single image (optional `folder_id`) |
| POST | `/upload/batch` | Upload multiple images (optional `folder_id`) |
| GET | `/` | List images (filters: `status`, `min_status`, `source`, pagination) |
| GET | `/stats` | Pipeline statistics (counts by status) |
| GET | `/{id}` | Get image with metadata |
| DELETE | `/{id}` | Delete image and files |
| GET | `/{id}/similar` | Find similar images by embedding distance |
| GET | `/{id}/folders` | Get folders containing this image |
| POST | `/{id}/reprocess` | Reprocess through full pipeline (optional prompt overrides) |
| POST | `/{id}/tag` | Tag only (optional custom prompt) |
| POST | `/{id}/describe` | Describe only (optional custom prompt) |
| POST | `/{id}/embed` | Generate embedding only |
| GET | `/thumbnails/{filename}` | Serve thumbnail file |
| GET | `/files/{filename}` | Serve full image file |

### Folders (`/api/folders`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/` | Create folder (name, description) |
| GET | `/` | List folders with preview images |
| GET | `/{id}` | Get folder details |
| PATCH | `/{id}` | Update folder name/description |
| DELETE | `/{id}` | Delete folder (preserves images) |
| POST | `/{id}/images` | Add images to folder |
| DELETE | `/{id}/images` | Remove images from folder |
| GET | `/{id}/images` | List folder images (with status filters) |
| POST | `/{id}/reprocess` | Reprocess all images in folder |

### Clusters (`/api/clusters`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List clusters from latest run (filters: `include_archived`) |
| GET | `/{id}` | Get cluster details with images |
| GET | `/{id}/images` | Get paginated cluster images |
| PATCH | `/{id}/rename` | Rename cluster |
| POST | `/{id}/pin` | Toggle pin status |
| POST | `/{id}/archive` | Archive cluster |
| POST | `/merge` | Merge multiple clusters |
| DELETE | `/{id}/images/{image_id}` | Exclude image from cluster |
| POST | `/{id}/summarize` | Regenerate AI summary |
| POST | `/recluster` | Trigger re-clustering (optional method override) |
| POST | `/summarize-all` | Summarize all unsummarized clusters |
| GET | `/{id}/export` | Export cluster data (JSON or ZIP) |

### Search (`/api/search`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/` | Hybrid semantic + text search (adaptive weighting) |
| GET | `/filter` | Filter images by tags |
| GET | `/tags` | Get all tags sorted by frequency |

### Jobs (`/api/jobs`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List jobs (filters: `job_type`, `status`, `image_id`) |
| GET | `/{id}` | Get job details |
| POST | `/{id}/cancel` | Cancel running job |
| DELETE | `/{id}` | Delete job record |
| GET | `/{id}/images` | Get images in a batch job |
| POST | `/pipeline/full` | Trigger full pipeline for all pending images |
| POST | `/pipeline/tag` | Tag all untagged images |
| POST | `/pipeline/describe` | Describe all undescribed images |
| POST | `/pipeline/embed` | Embed all unembedded images |
| POST | `/pipeline/reprocess-all` | Reprocess all images from scratch |
| POST | `/pipeline/reprocess-failed` | Reprocess only failed images |
| POST | `/pipeline/reprocess-selected` | Reprocess specific image IDs |

### Settings (`/api/settings`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/presets` | List all prompt presets |
| POST | `/presets` | Create new preset |
| GET | `/presets/{id}` | Get preset |
| PUT | `/presets/{id}` | Update preset |
| DELETE | `/presets/{id}` | Delete preset (cannot delete active) |
| POST | `/presets/{id}/activate` | Set preset as default |
| GET | `/prompts` | Get current default prompts |
| PUT | `/prompts` | Update active preset prompts |
| POST | `/prompts/reset` | Reset prompts to factory defaults |
| POST | `/prompts/suggest` | AI-powered prompt suggestion |
| GET | `/clustering` | Get clustering configuration |
| PUT | `/clustering` | Update clustering config |
| POST | `/clustering/reset` | Reset clustering to defaults |

### Logs (`/api/logs`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Query logs (filters: `category`, `level`, `image_id`, `job_id`, `search`) |
| GET | `/stats` | Log statistics (total, API calls, errors, tokens) |
| DELETE | `/cleanup` | Delete logs older than N days |

## Database Models

### Image + ImageMetadata (1:1)
Core image record with processing status tracking (PENDING → INGESTED → TAGGED → DESCRIBED → EMBEDDED → CLUSTERED). Metadata stores tags (flat string array), long description, 1536-dim embedding vector, dominant colors, and model provenance. SHA-256 hash for deduplication, perceptual hash for visual similarity, tsvector for full-text search.

### Cluster + ClusterMembership
Clusters from a specific clustering run (identified by `run_id`). Each cluster has a centroid embedding, AI-generated summary, common tags, and representative images. Memberships link images to clusters with distance-to-centroid scores. Supports pinning, archiving, renaming, and user-excluded outliers.

### Job
Tracks async Celery tasks with type (INGEST, TAG, DESCRIBE, EMBED, CLUSTER, SUMMARIZE_CLUSTER, FULL_PIPELINE, REPROCESS, BATCH_REPROCESS), status, progress/total counters, parameters, result data, and error messages.

### Folder + FolderImage
User-created folders for organizing images. Many-to-many relationship — an image can belong to multiple folders. Folder deletion preserves images.

### PromptPreset
Named pairs of tag guidance + description guidance prompts. One preset is marked as default and used for pipeline processing. Prompts are composed by wrapping user guidance in system-level prompt templates.

### PipelineLog
Structured log entries categorized as API_CALL, TASK, PIPELINE, or SYSTEM. Tracks provider, model, operation, duration, token counts, success/failure, and arbitrary extra data. Indexed for efficient filtering.

### AppSetting
Key-value store for application configuration (clustering config, legacy prompt settings).

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | — | OpenAI API key (required) |
| `ANTHROPIC_API_KEY` | — | Anthropic API key (optional) |
| `DATABASE_URL` | `postgresql://postgres:postgres@postgres:5432/design_pipeline` | PostgreSQL connection |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | `redis://redis:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://redis:6379/2` | Celery result store |
| `SECRET_KEY` | `change-me-in-production` | Encryption key for stored API keys |
| `DEFAULT_VISION_PROVIDER` | `openai` | Vision provider (openai/anthropic) |
| `DEFAULT_EMBEDDING_PROVIDER` | `openai` | Embedding provider |
| `OPENAI_VISION_MODEL` | `gpt-4o` | OpenAI vision model |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model |
| `ANTHROPIC_VISION_MODEL` | `claude-sonnet-4-20250514` | Anthropic vision model |
| `STORAGE_BACKEND` | `local` | Storage backend (local/s3/gcs) |
| `LOCAL_STORAGE_PATH` | `./storage` | Local image storage path |
| `WATCH_FOLDER_PATH` | `./watch_folder` | Folder watcher path |

### Clustering Configuration (via Settings UI or API)

| Parameter | Default | Description |
|-----------|---------|-------------|
| `method` | `hdbscan` | Algorithm: hdbscan, kmeans, graph |
| `use_umap` | `true` | Enable UMAP dimensionality reduction |
| `umap_n_components` | `10` | UMAP output dimensions |
| `umap_n_neighbors` | `15` | UMAP local structure size |
| `umap_min_dist` | `0.0` | UMAP point packing tightness |
| `umap_metric` | `cosine` | UMAP distance metric |
| `hdbscan_min_cluster_size` | `3` | Smallest valid HDBSCAN cluster |
| `hdbscan_min_samples` | `2` | HDBSCAN density threshold |
| `hdbscan_cluster_selection_method` | `eom` | HDBSCAN selection: eom or leaf |
| `kmeans_max_clusters` | `50` | Upper bound for auto-K selection |

## Development Setup

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Start PostgreSQL and Redis
docker compose up -d postgres redis

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --reload --port 8000

# Start Celery worker (separate terminal)
celery -A app.workers.celery_app worker --loglevel=info

# Start clustering worker (separate terminal)
celery -A app.workers.celery_app worker -Q clustering --loglevel=info
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

## Extending

### Adding a New AI Provider

1. Create provider class in `backend/app/providers/`:

```python
from app.providers.base import BaseTagger, TaggingResult

class MyTagger(BaseTagger):
    async def tag_image(self, image_data: bytes, mime_type: str, tag_prompt: str) -> TaggingResult:
        # Your implementation
        return TaggingResult(tags=["tag1", "tag2"], model="my-model", prompt_version="v1")

    def get_model_name(self) -> str:
        return "my-model"
```

2. Register in `backend/app/providers/__init__.py`:

```python
def get_tagger(provider: str | None = None) -> BaseTagger:
    if provider == "my_provider":
        return MyTagger()
    # ...
```

### Adding a New Image Source

1. Add source enum in `backend/app/models/image.py`
2. Create ingestion logic using `ImageService.ingest_image()`
3. Call `process_image_pipeline.delay(image.id)` to queue processing

## Project Structure

```
.
├── backend/
│   ├── app/
│   │   ├── api/              # FastAPI route handlers
│   │   │   ├── images.py     # Image CRUD, upload, reprocess
│   │   │   ├── clusters.py   # Cluster management, export
│   │   │   ├── search.py     # Hybrid search, tag filter
│   │   │   ├── jobs.py       # Job monitoring, pipeline triggers
│   │   │   ├── settings.py   # Prompts, presets, clustering config
│   │   │   ├── logs.py       # Pipeline log queries
│   │   │   └── folders.py    # Folder management
│   │   ├── core/             # App configuration
│   │   ├── db/               # Database session management
│   │   ├── models/           # SQLAlchemy models
│   │   │   ├── image.py      # Image + ImageMetadata
│   │   │   ├── cluster.py    # Cluster + ClusterMembership
│   │   │   ├── job.py        # Job tracking
│   │   │   ├── folder.py     # Folder + FolderImage
│   │   │   ├── prompt_preset.py  # Prompt presets
│   │   │   ├── pipeline_log.py   # Structured logs
│   │   │   ├── settings.py   # AppSetting key-value
│   │   │   └── api_key.py    # Encrypted API key storage
│   │   ├── providers/        # AI provider abstractions
│   │   │   ├── base.py       # Interfaces: BaseTagger, BaseDescriber, BaseEmbedder, BaseClusterSummarizer
│   │   │   ├── openai_provider.py   # OpenAI implementations
│   │   │   └── anthropic_provider.py # Anthropic implementations
│   │   ├── schemas/          # Pydantic request/response models
│   │   ├── services/         # Business logic layer
│   │   │   ├── image_service.py      # Image CRUD, metadata
│   │   │   ├── cluster_service.py    # Cluster CRUD, merge
│   │   │   ├── clustering.py         # HDBSCAN/KMeans/Graph algorithms
│   │   │   ├── storage.py            # File storage, thumbnails, hashing
│   │   │   ├── settings_service.py   # Prompts, presets, clustering config
│   │   │   ├── folder_service.py     # Folder CRUD, image assignment
│   │   │   ├── log_service.py        # Pipeline log writes/queries
│   │   │   ├── api_key_service.py    # Encrypted API key management
│   │   │   └── encryption.py         # Fernet symmetric encryption
│   │   ├── workers/          # Celery task definitions
│   │   │   ├── celery_app.py # Celery config, queues, rate limits
│   │   │   └── tasks.py      # All async tasks
│   │   └── main.py           # FastAPI app entry point
│   ├── migrations/           # Alembic migrations (10 versions)
│   ├── scripts/              # Utility scripts
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   └── src/
│       ├── app/              # Next.js 14 App Router pages
│       │   ├── page.tsx              # Home (clusters dashboard)
│       │   ├── layout.tsx            # Root layout with sidebar
│       │   ├── images/
│       │   │   ├── page.tsx          # Folders list
│       │   │   ├── all/page.tsx      # All images grid
│       │   │   └── folder/[id]/page.tsx  # Folder detail
│       │   ├── upload/page.tsx       # Upload page
│       │   ├── search/page.tsx       # Search page
│       │   ├── clusters/[id]/page.tsx # Cluster detail
│       │   ├── jobs/page.tsx         # Jobs monitor
│       │   ├── debug/page.tsx        # Debug logs
│       │   └── settings/page.tsx     # Settings
│       ├── components/       # Reusable UI components
│       │   ├── Header.tsx            # Top bar with search, stats
│       │   ├── Sidebar.tsx           # Navigation sidebar
│       │   ├── ImageCard.tsx         # Image thumbnail card
│       │   ├── ImageDrawer.tsx       # Image detail slide-over
│       │   ├── ImageGrid.tsx         # Paginated grid with filters
│       │   ├── ClusterCard.tsx       # Cluster summary card
│       │   ├── FolderCard.tsx        # Folder preview card
│       │   └── PipelineProgress.tsx  # Visual status indicator
│       ├── lib/
│       │   ├── api.ts        # Typed Axios API client
│       │   ├── utils.ts      # Formatting helpers
│       │   └── pipeline.ts   # Pipeline status logic
│       └── types/
│           └── index.ts      # TypeScript type definitions
├── docker/
│   └── init-db.sql           # pgvector extension init
├── docker-compose.yml        # Service orchestration
├── storage/                  # Image files (gitignored)
├── watch_folder/             # Auto-ingest folder
├── .env                      # API keys (gitignored)
├── CLAUDE.md                 # Claude Code instructions
└── README.md                 # This file
```

## Service URLs

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/api/docs |
| API Docs (ReDoc) | http://localhost:8000/api/redoc |

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Next.js 14, React 18, TypeScript, TanStack Query, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy 2.0, Pydantic, Alembic |
| Database | PostgreSQL 16 + pgvector 0.7.0 |
| Queue | Celery + Redis 7 |
| AI (Vision) | OpenAI GPT-4o, Anthropic Claude Sonnet |
| AI (Embeddings) | OpenAI text-embedding-3-small (1536 dims) |
| ML | HDBSCAN, scikit-learn, UMAP, numpy |
| Image Processing | Pillow, imagehash |
| Deployment | Docker Compose |

## License

MIT
