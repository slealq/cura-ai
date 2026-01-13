"""Search API endpoints."""
import logging
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import get_db
from app.models import Image, ImageMetadata
from app.providers import get_embedder
from app.schemas import ImageResponse, SearchRequest, SearchResponse, TagFilterOptions
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
    import asyncio
    loop = asyncio.get_event_loop()
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
    style: list[str] | None = Query(None),
    subject: list[str] | None = Query(None),
    medium: list[str] | None = Query(None),
    mood: list[str] | None = Query(None),
    color_palette: list[str] | None = Query(None),
    lighting: list[str] | None = Query(None),
    materials: list[str] | None = Query(None),
    composition: list[str] | None = Query(None),
    typography: list[str] | None = Query(None),
    era_reference: list[str] | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Filter images by tag categories using JSON queries."""
    # Build tag filters
    filters = {}
    if style:
        filters["style"] = style
    if subject:
        filters["subject"] = subject
    if medium:
        filters["medium"] = medium
    if mood:
        filters["mood"] = mood
    if color_palette:
        filters["color_palette"] = color_palette
    if lighting:
        filters["lighting"] = lighting
    if materials:
        filters["materials"] = materials
    if composition:
        filters["composition"] = composition
    if typography:
        filters["typography"] = typography
    if era_reference:
        filters["era_reference"] = era_reference

    if not filters:
        # No filters, return recent images
        image_service = get_image_service(db)
        images = image_service.get_images(skip=skip, limit=limit)
        return [ImageResponse.model_validate(img) for img in images]

    # Build dynamic SQL for JSON filtering
    conditions = []
    params = {"skip": skip, "limit": limit}

    for i, (category, values) in enumerate(filters.items()):
        # Check if any of the values are in the tags array for this category
        # Using PostgreSQL JSONB operators
        value_conditions = []
        for j, value in enumerate(values):
            param_name = f"tag_{i}_{j}"
            value_conditions.append(f"m.tags->'{category}' @> :{param_name}::jsonb")
            params[param_name] = f'["{value}"]'

        if value_conditions:
            conditions.append(f"({' OR '.join(value_conditions)})")

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


@router.get("/tags", response_model=TagFilterOptions)
async def get_available_tags(db: Session = Depends(get_db)):
    """Get all available tag values for filtering UI."""
    # Query all tags from metadata
    results = db.query(ImageMetadata.tags).filter(ImageMetadata.tags.isnot(None)).all()

    # Aggregate unique values per category
    categories: dict[str, Counter] = {
        "style": Counter(),
        "subject": Counter(),
        "medium": Counter(),
        "mood": Counter(),
        "color_palette": Counter(),
        "lighting": Counter(),
        "materials": Counter(),
        "composition": Counter(),
        "typography": Counter(),
        "era_reference": Counter(),
    }

    for (tags,) in results:
        if not tags:
            continue
        for category, values in tags.items():
            if category in categories and values:
                categories[category].update(values)

    # Convert to sorted lists (most common first)
    return TagFilterOptions(
        style=[t for t, _ in categories["style"].most_common(50)],
        subject=[t for t, _ in categories["subject"].most_common(50)],
        medium=[t for t, _ in categories["medium"].most_common(50)],
        mood=[t for t, _ in categories["mood"].most_common(50)],
        color_palette=[t for t, _ in categories["color_palette"].most_common(50)],
        lighting=[t for t, _ in categories["lighting"].most_common(50)],
        materials=[t for t, _ in categories["materials"].most_common(50)],
        composition=[t for t, _ in categories["composition"].most_common(50)],
        typography=[t for t, _ in categories["typography"].most_common(50)],
        era_reference=[t for t, _ in categories["era_reference"].most_common(50)],
    )
