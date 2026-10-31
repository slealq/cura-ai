"""Pydantic schemas for API request/response models."""
from datetime import datetime
from typing import Any  # noqa: F401

from pydantic import BaseModel, Field, computed_field, field_validator

from app.services.pipeline_errors import readable_error


# Image schemas
class ImageBase(BaseModel):
    """Base image schema."""

    original_filename: str | None = None
    source: str
    width: int | None = None
    height: int | None = None


class ImageMetadataResponse(BaseModel):
    """Image metadata response."""

    tags: list[str] = Field(default_factory=list)
    dominant_colors: list[dict] = Field(default_factory=list)
    description_long: str | None = None
    tagging_model: str | None = None
    caption_model: str | None = None
    embedding_model: str | None = None
    tagged_at: datetime | None = None
    described_at: datetime | None = None
    embedded_at: datetime | None = None
    tagging_duration_ms: int | None = None
    caption_duration_ms: int | None = None
    embedding_duration_ms: int | None = None

    class Config:
        from_attributes = True


class ProcessingCostOperation(BaseModel):
    """Single processing operation cost."""

    operation: str
    provider: str
    model: str
    sparks: float
    input_tokens: int | None = None
    output_tokens: int | None = None


class ProcessingCostResponse(BaseModel):
    """Per-image processing cost breakdown."""

    operations: list[ProcessingCostOperation] = Field(default_factory=list)
    total_sparks: float = 0


class ImageResponse(BaseModel):
    """Image response schema."""

    id: int
    source: str
    original_filename: str | None
    generated_image_id: int | None = None
    object_key: str
    width: int | None
    height: int | None
    file_size: int | None
    mime_type: str | None
    status: str
    error_message: str | None = None
    thumbnail_uri_small: str | None
    thumbnail_uri_medium: str | None
    thumbnail_uri_large: str | None
    created_at: datetime
    ingested_at: datetime | None
    metadata: ImageMetadataResponse | None = Field(default=None, validation_alias="image_metadata")

    @computed_field
    @property
    def thumbnail_url(self) -> str | None:
        from app.services.storage import get_storage_service

        return get_storage_service().generate_thumbnail_sas_url(
            self.thumbnail_uri_medium or self.thumbnail_uri_small
        )

    @computed_field
    @property
    def thumbnail_urls(self) -> dict[str, str]:
        """Sign existing variants locally; never probe storage per image."""
        from app.services.storage import get_storage_service

        storage = get_storage_service()
        return {
            size: storage.generate_thumbnail_sas_url(uri)
            for size, uri in (("200", self.thumbnail_uri_small),
                              ("400", self.thumbnail_uri_medium),
                              ("800", self.thumbnail_uri_large))
            if uri
        }

    @computed_field
    @property
    def image_url(self) -> str:
        from app.services.storage import get_storage_service

        storage = get_storage_service()
        if storage.storage_backend == "azure":
            return storage._generate_sas_url(f"images/{self.object_key}")
        return f"/api/images/files/{self.object_key}"

    @field_validator("error_message")
    @classmethod
    def safe_error_message(cls, value):
        return readable_error(value) if value is not None else None

    class Config:
        from_attributes = True
        populate_by_name = True


class ImageListResponse(BaseModel):
    """Paginated image list response."""

    items: list[ImageResponse]
    total: int
    skip: int
    limit: int


# Cluster schemas
class ClusterPreviewImage(BaseModel):
    id: int
    thumbnail_url: str
    width: int | None
    height: int | None


class ClusterResponse(BaseModel):
    """Cluster response schema."""

    id: int
    method: str
    run_id: str
    size: int
    summary_title: str | None
    summary_description: str | None
    common_tags: list[str] = Field(default_factory=list)
    representative_image_ids: list[int] = Field(default_factory=list)
    display_name: str | None
    is_pinned: bool
    is_archived: bool
    cover_thumbnail_url: str | None = None
    preview_images: list[ClusterPreviewImage] = Field(default_factory=list)
    is_unclustered: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ClusterOverview(BaseModel):
    clusters: int = 0
    grouped: int = 0
    unclustered: ClusterResponse | None = None
    largest: list[ClusterResponse] = Field(default_factory=list)


class ClusterListResponse(BaseModel):
    """Paginated cluster list response."""

    overview: ClusterOverview = Field(default_factory=ClusterOverview)
    items: list[ClusterResponse]
    total: int
    skip: int
    limit: int


class ClusterDetailResponse(ClusterResponse):
    """Cluster detail with images."""

    images: list[ImageResponse] = Field(default_factory=list)


class ClusterRenameRequest(BaseModel):
    """Request to rename a cluster."""

    display_name: str = Field(..., min_length=1, max_length=256)


class ClusterMergeRequest(BaseModel):
    """Request to merge clusters."""

    cluster_ids: list[int] = Field(..., min_length=2)
    new_name: str | None = None


# Job schemas
class JobResponse(BaseModel):
    """Job response schema."""

    id: int
    celery_task_id: str | None
    job_type: str
    status: str
    progress: int
    total_items: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    result: dict | None = None
    parameters: dict | None = None
    image_id: int | None = None
    image_filename: str | None = None
    image_thumbnail: str | None = None
    charged_cost: float | None = None

    @field_validator("error_message")
    @classmethod
    def safe_error_message(cls, value):
        return readable_error(value) if value is not None else None

    class Config:
        from_attributes = True


class StepResponse(BaseModel):
    """Response from triggering a single image processing step."""

    status: str
    image_id: int
    step: str
    job_id: int


class JobListResponse(BaseModel):
    """Paginated job list response."""

    items: list[JobResponse]
    total: int
    skip: int
    limit: int


# Upload schemas
class UploadResponse(BaseModel):
    """Upload response schema."""

    image_id: int
    filename: str
    status: str
    message: str


class BatchUploadResponse(BaseModel):
    """Batch upload response schema."""

    uploaded: list[UploadResponse]
    failed: list[dict[str, str]]
    job_id: int | None = None
    folder_error: str | None = None


# Search schemas
class SearchRequest(BaseModel):
    """Search request schema."""

    query: str = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class ScoredImageResponse(BaseModel):
    """Image with search relevance scores."""

    image: ImageResponse
    score: float
    semantic_score: float
    text_score: float


class SearchResponse(BaseModel):
    """Search response schema."""

    results: list[ScoredImageResponse]
    query: str
    total: int


# Stats schemas
class PipelineStats(BaseModel):
    """Pipeline statistics."""

    total_images: int
    pending: int
    ingested: int
    tagged: int
    described: int
    embedded: int
    clustered: int
    failed: int
    total_clusters: int


# Trigger schemas
class TriggerClusteringRequest(BaseModel):
    """Request to trigger clustering."""

    method: str | None = Field(default=None, description="Clustering method: hdbscan, kmeans, graph")


class TriggerClusteringResponse(BaseModel):
    """Response from triggering clustering."""

    job_id: int
    status: str
    message: str


# Batch reprocess schemas
class BatchReprocessRequest(BaseModel):
    """Request to reprocess specific images."""

    image_ids: list[int] = Field(..., min_length=1)


class BatchJobImageInfo(BaseModel):
    """Image info for batch job popover."""

    id: int
    original_filename: str | None
    thumbnail: str | None
