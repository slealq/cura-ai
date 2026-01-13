# Design Idea Ingestion Pipeline

Automatically ingest, tag, cluster, and browse design inspiration images using AI.

## Features

- **Auto-tagging**: Extract structured metadata (style, subject, mood, materials, etc.) using vision AI
- **Auto-descriptions**: Generate captions and design notes for each image
- **Semantic clustering**: Group similar images using embeddings and HDBSCAN
- **Web UI**: Browse clusters, search semantically, filter by tags
- **Multiple ingestion modes**: Upload, folder watcher, cloud storage (planned)
- **Provider abstraction**: Swap between OpenAI/Anthropic for vision models

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Next.js UI    │────▶│   FastAPI       │────▶│   PostgreSQL    │
│   (Frontend)    │     │   (Backend)     │     │   + pgvector    │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                        ┌────────▼────────┐
                        │  Celery Workers │
                        │  (Processing)   │
                        └────────┬────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌─────────┐  ┌─────────┐  ┌─────────┐
              │ Tagger  │  │Captioner│  │Embedder │
              │ (GPT-4o)│  │ (GPT-4o)│  │(OpenAI) │
              └─────────┘  └─────────┘  └─────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- OpenAI API key (or Anthropic API key)

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
docker-compose up -d
```

This starts:
- PostgreSQL with pgvector (port 5432)
- Redis (port 6379)
- FastAPI backend (port 8000)
- Celery workers
- Next.js frontend (port 3000)

### 3. Initialize database

```bash
docker-compose exec backend python scripts/init_db.py
```

### 4. Access the UI

Open http://localhost:3000

### 5. Upload images

Either:
- Use the Upload page in the UI
- Drop images in `./watch_folder/` (auto-ingested)
- Use the API directly

## Development Setup

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e ".[dev]"

# Start PostgreSQL and Redis
docker-compose up -d postgres redis

# Initialize database
python scripts/init_db.py

# Start API server
uvicorn app.main:app --reload --port 8000

# Start Celery worker (in another terminal)
celery -A app.workers.celery_app worker --loglevel=info
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
```

## API Endpoints

### Images

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/images/upload` | Upload single image |
| POST | `/api/images/upload/batch` | Upload multiple images |
| GET | `/api/images` | List images (with filters) |
| GET | `/api/images/{id}` | Get image details |
| GET | `/api/images/{id}/similar` | Get similar images |
| POST | `/api/images/{id}/reprocess` | Reprocess image |
| GET | `/api/images/stats` | Pipeline statistics |

### Clusters

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/clusters` | List clusters |
| GET | `/api/clusters/{id}` | Get cluster details |
| PATCH | `/api/clusters/{id}/rename` | Rename cluster |
| POST | `/api/clusters/{id}/pin` | Toggle pin status |
| POST | `/api/clusters/{id}/archive` | Archive cluster |
| POST | `/api/clusters/merge` | Merge clusters |
| POST | `/api/clusters/recluster` | Trigger re-clustering |
| GET | `/api/clusters/{id}/export` | Export cluster (JSON/ZIP) |

### Search

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/search` | Semantic search |
| GET | `/api/search/filter` | Filter by tags |
| GET | `/api/search/tags` | Get available tags |

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/jobs` | List jobs |
| GET | `/api/jobs/{id}` | Get job status |
| POST | `/api/jobs/{id}/cancel` | Cancel job |
| POST | `/api/jobs/pipeline/full` | Run full pipeline |

## Tag Taxonomy

Images are tagged with a structured taxonomy:

```json
{
  "style": ["minimal", "editorial", "brutalist", "organic", ...],
  "subject": ["portrait", "product", "interior", "abstract", ...],
  "medium": ["photo", "3d-render", "illustration", "vector", ...],
  "mood": ["calm", "energetic", "premium", "dramatic", ...],
  "color_palette": ["warm", "cool", "neutral", "vibrant", ...],
  "lighting": ["natural", "studio", "soft", "dramatic", ...],
  "materials": ["wood", "metal", "glass", "fabric", ...],
  "composition": ["centered", "symmetrical", "negative-space", ...],
  "typography": ["none", "serif", "sans-serif", "script", ...],
  "era_reference": ["contemporary", "retro", "mid-century", ...]
}
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis URL |
| `OPENAI_API_KEY` | - | OpenAI API key (required) |
| `ANTHROPIC_API_KEY` | - | Anthropic API key (optional) |
| `DEFAULT_VISION_PROVIDER` | `openai` | Vision model provider |
| `DEFAULT_EMBEDDING_PROVIDER` | `openai` | Embedding provider |
| `CLUSTERING_METHOD` | `hdbscan` | Clustering algorithm |
| `LOCAL_STORAGE_PATH` | `./storage` | Image storage path |
| `WATCH_FOLDER_PATH` | `./watch_folder` | Folder watcher path |

### Switching AI Providers

Edit `backend/.env`:

```bash
# Use Anthropic Claude for vision
DEFAULT_VISION_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

## Adding a New Image Source

1. Add source enum in `backend/app/models/image.py`:
```python
class ImageSource(str, enum.Enum):
    # existing sources...
    MY_SOURCE = "my_source"
```

2. Create ingestion script in `backend/scripts/`:
```python
from app.services.image_service import get_image_service
from app.models import ImageSource

async def ingest_from_my_source():
    db = SessionLocal()
    image_service = get_image_service(db)

    image = await image_service.ingest_image(
        file_data=...,
        filename="...",
        source=ImageSource.MY_SOURCE,
        original_uri="...",
    )

    process_image_pipeline.delay(image.id)
```

## Adding a New AI Provider

1. Create provider class in `backend/app/providers/`:

```python
from app.providers.base import BaseTagger, TaggingResult

class MyTagger(BaseTagger):
    async def tag_image(self, image_data: bytes, mime_type: str) -> TaggingResult:
        # Your implementation
        return TaggingResult(
            tags={...},
            model="my-model",
            prompt_version="v1.0.0",
        )

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

## Processing Pipeline

1. **Ingest**: Store image, generate thumbnails, compute hash
2. **Tag**: Extract structured tags using vision AI
3. **Describe**: Generate caption and design notes
4. **Embed**: Create text embedding from tags + description
5. **Cluster**: Group images using HDBSCAN on embeddings
6. **Summarize**: Generate cluster titles and descriptions

## Folder Structure

```
.
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI endpoints
│   │   ├── core/          # Configuration
│   │   ├── db/            # Database setup
│   │   ├── models/        # SQLAlchemy models
│   │   ├── providers/     # AI provider implementations
│   │   ├── schemas/       # Pydantic schemas
│   │   ├── services/      # Business logic
│   │   └── workers/       # Celery tasks
│   ├── migrations/        # Alembic migrations
│   └── scripts/           # Utility scripts
├── frontend/
│   └── src/
│       ├── app/           # Next.js pages
│       ├── components/    # React components
│       ├── lib/           # API client, utilities
│       └── types/         # TypeScript types
├── docker/                # Docker configuration
├── storage/               # Image storage (gitignored)
└── watch_folder/          # Auto-ingest folder
```

## Scripts

```bash
# Initialize database
python scripts/init_db.py

# Seed sample images
python scripts/seed_sample_images.py --count 10

# Start folder watcher
python scripts/folder_watcher.py --watch-path ./watch_folder
```

## License

MIT
