"""Search API endpoints."""
import logging
from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.base import get_db
from app.models import ImageMetadata
from app.models.user import User
from app.providers import get_embedder
from app.schemas import ImageResponse, ScoredImageResponse, SearchRequest, SearchResponse
from app.services.image_service import get_image_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/search", tags=["search"])


def _adaptive_weights(query: str) -> tuple[float, float]:
    """Return (semantic_weight, text_weight) based on query word count."""
    word_count = len(query.split())
    if word_count <= 2:
        return 0.4, 0.6
    elif word_count <= 5:
        return 0.6, 0.4
    else:
        return 0.8, 0.2


@router.post("", response_model=SearchResponse)
async def semantic_search(
    request: SearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Hybrid search: combines semantic embedding similarity with keyword matching.

    Short queries lean towards keyword matching; longer queries lean towards semantic.
    """
    embedder = get_embedder(db=db, user_id=current_user.id)
    query_embedding = await embedder.embed_text(request.query)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding.embedding) + "]"

    sw, tw = _adaptive_weights(request.query)

    sql_query = text("""
        WITH scored AS (
            SELECT i.id,
                (1.0 - (m.embedding <=> :embedding) / 2.0) AS semantic_score,
                CASE WHEN m.search_vector IS NOT NULL
                     AND plainto_tsquery('english', :query_text) != ''::tsquery
                THEN ts_rank_cd(m.search_vector, plainto_tsquery('english', :query_text))
                ELSE 0 END AS raw_text_score
            FROM images i
            JOIN image_metadata m ON i.id = m.image_id
            WHERE m.embedding IS NOT NULL
            AND i.user_id = :user_id
        )
        SELECT id, semantic_score,
            raw_text_score / (raw_text_score + 1.0) AS text_score,
            (:sw * semantic_score + :tw * (raw_text_score / (raw_text_score + 1.0))) AS combined_score
        FROM scored
        ORDER BY combined_score DESC
        LIMIT :limit
    """)

    result = db.execute(sql_query, {
        "embedding": embedding_str,
        "query_text": request.query,
        "sw": sw,
        "tw": tw,
        "limit": request.limit,
        "user_id": current_user.id,
    })
    rows = result.fetchall()

    image_ids = [row[0] for row in rows]
    scores_by_id = {
        row[0]: {
            "semantic_score": float(row[1]),
            "text_score": float(row[2]),
            "combined_score": float(row[3]),
        }
        for row in rows
    }

    image_service = get_image_service(db, current_user.id)
    images = image_service.get_images_by_ids(image_ids)

    id_to_image = {img.id: img for img in images}
    scored_results = []
    for img_id in image_ids:
        if img_id in id_to_image:
            s = scores_by_id[img_id]
            scored_results.append(ScoredImageResponse(
                image=ImageResponse.model_validate(id_to_image[img_id]),
                score=s["combined_score"],
                semantic_score=s["semantic_score"],
                text_score=s["text_score"],
            ))

    return SearchResponse(
        results=scored_results,
        query=request.query,
        total=len(scored_results),
    )


@router.get("/filter", response_model=list[ImageResponse])
async def filter_images(
    tags: list[str] | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Filter images by tags using JSON array containment."""
    if not tags:
        # No filters, return recent images
        image_service = get_image_service(db, current_user.id)
        images = image_service.get_images(skip=skip, limit=limit)
        return [ImageResponse.model_validate(img) for img in images]

    # Build dynamic SQL for JSON array containment
    # Each tag must be present in the tags JSON array
    conditions = ["i.user_id = :user_id"]
    params = {"skip": skip, "limit": limit, "user_id": current_user.id}

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

    image_service = get_image_service(db, current_user.id)
    images = image_service.get_images_by_ids(image_ids)

    return [ImageResponse.model_validate(img) for img in images]


@router.get("/tags", response_model=list[str])
async def get_available_tags(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get all available tag values for filtering UI, sorted by frequency."""
    results = db.query(ImageMetadata.tags).filter(ImageMetadata.tags.isnot(None)).all()

    counter = Counter()
    for (tags,) in results:
        if tags and isinstance(tags, list):
            counter.update(tags)

    return [tag for tag, _ in counter.most_common(100)]
