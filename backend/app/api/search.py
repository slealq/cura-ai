"""Search API endpoints."""
import logging
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models import Image, ImageMetadata
from app.providers import get_embedder
from app.schemas import ImageResponse, SearchRequest, SearchResponse
from app.services.image_service import get_image_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def semantic_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
):
    """
    Perform semantic search on image descriptions using embeddings.

    This searches across all image descriptions and tags using vector similarity.
    """
    # Generate embedding for the query
    embedder = get_embedder()
    query_embedding = await embedder.embed_text(request.query)

    embedding_str = "[" + ",".join(str(x) for x in query_embedding.embedding) + "]"

    # Search using pgvector cosine distance
    sql_query = text("""
        SELECT i.id, m.embedding <-> :embedding AS distance
        FROM images i
        JOIN image_metadata m ON i.id = m.image_id
        WHERE m.embedding IS NOT NULL
        ORDER BY m.embedding <-> :embedding
        LIMIT :limit
    """)

    result = db.execute(sql_query, {"embedding": embedding_str, "limit": request.limit})
    rows = result.fetchall()

    image_ids = [row[0] for row in rows]

    image_service = get_image_service(db)
    images = image_service.get_images_by_ids(image_ids)

    # Maintain search order
    id_to_image = {img.id: img for img in images}
    ordered_images = [id_to_image[img_id] for img_id in image_ids if img_id in id_to_image]

    return SearchResponse(
        images=[ImageResponse.model_validate(img) for img in ordered_images],
        query=request.query,
        total=len(ordered_images),
    )


@router.get("/filter", response_model=list[ImageResponse])
async def filter_images(
    tags: list[str] | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Filter images by tags using JSON array containment."""
    if not tags:
        # No filters, return recent images
        image_service = get_image_service(db)
        images = image_service.get_images(skip=skip, limit=limit)
        return [ImageResponse.model_validate(img) for img in images]

    # Build dynamic SQL for JSON array containment
    # Each tag must be present in the tags JSON array
    conditions = []
    params = {"skip": skip, "limit": limit}

    for i, tag in enumerate(tags):
        param_name = f"tag_{i}"
        conditions.append(f"m.tags::jsonb @> :{param_name}::jsonb")
        params[param_name] = f'["{tag}"]'

    where_clause = " AND ".join(conditions)

    sql_query = text(f"""
        SELECT i.id
        FROM images i
        JOIN image_metadata m ON i.id = m.image_id
        WHERE {where_clause}
        ORDER BY i.created_at DESC
        OFFSET :skip
        LIMIT :limit
    """)

    result = db.execute(sql_query, params)
    image_ids = [row[0] for row in result]

    image_service = get_image_service(db)
    images = image_service.get_images_by_ids(image_ids)

    return [ImageResponse.model_validate(img) for img in images]


@router.get("/tags", response_model=list[str])
async def get_available_tags(db: Session = Depends(get_db)):
    """Get all available tag values for filtering UI, sorted by frequency."""
    results = db.query(ImageMetadata.tags).filter(ImageMetadata.tags.isnot(None)).all()

    counter = Counter()
    for (tags,) in results:
        if tags and isinstance(tags, list):
            counter.update(tags)

    return [tag for tag, _ in counter.most_common(100)]
