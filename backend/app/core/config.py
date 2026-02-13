"""Application configuration settings."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "Design Idea Pipeline"
    app_version: str = "0.1.0"
    debug: bool = False
    secret_key: str = "change-me-in-production"

    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/design_pipeline"

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # Storage
    storage_backend: Literal["local", "s3", "gcs", "azure"] = "local"
    local_storage_path: str = "./storage"
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    gcs_bucket: str = ""
    azure_storage_connection_string: str = ""
    azure_storage_container: str = "images"

    # Environment & CORS
    environment: Literal["local", "dev", "prod"] = "local"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"

    # Watch folder
    watch_folder_path: str = "./watch_folder"
    watch_folder_enabled: bool = True

    # AI Provider settings
    default_vision_provider: Literal["openai", "anthropic"] = "openai"
    default_embedding_provider: Literal["openai", "local"] = "openai"

    # OpenAI
    openai_api_key: str = ""
    openai_vision_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # Anthropic
    anthropic_api_key: str = ""
    anthropic_vision_model: str = "claude-sonnet-4-20250514"

    # fal.ai
    fal_api_key: str = ""

    # Generation / Training providers
    default_training_provider: str = "fal"
    default_generation_provider: str = "fal"
    default_base_model: str = "flux-dev"

    # Clustering
    clustering_method: Literal["hdbscan", "kmeans", "graph"] = "hdbscan"
    hdbscan_min_cluster_size: int = 3
    hdbscan_min_samples: int = 2
    kmeans_max_clusters: int = 50

    # Thumbnails
    thumbnail_sizes: list[int] = [200, 400, 800]

    # Rate limiting / batching
    batch_size: int = 10
    rate_limit_per_minute: int = 60

    # Auth / JWT
    jwt_secret_key: str = "change-me-in-production-jwt-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
