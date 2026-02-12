"""Provider factory for AI services."""
import logging
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.providers.anthropic_provider import (
    AnthropicClusterSummarizer,
    AnthropicDescriber,
    AnthropicTagger,
)
from app.providers.base import (
    BaseClusterSummarizer,
    BaseDescriber,
    BaseEmbedder,
    BaseGenerator,
    BaseTagger,
    BaseTrainer,
    ClusterSummaryResult,
    DescriptionResult,
    EmbeddingResult,
    GenerationResult,
    TaggingResult,
    TrainingResult,
)
from app.providers.fal_provider import FalGenerator, FalTrainer
from app.providers.openai_provider import (
    OpenAIClusterSummarizer,
    OpenAIDescriber,
    OpenAIEmbedder,
    OpenAITagger,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_config(db: Session | None):
    """Resolve API keys and provider config from DB (with env var fallback).

    Returns (key_map, provider_config) where key_map is {provider_name: key_value}
    and provider_config is the merged config dict.
    """
    if db is None:
        return {}, {}

    try:
        from app.models.api_key import APIProvider
        from app.services.api_key_service import get_api_key_service
        from app.services.settings_service import get_settings_service

        key_service = get_api_key_service(db)
        keys = {
            "openai": key_service.resolve_key(APIProvider.OPENAI),
            "anthropic": key_service.resolve_key(APIProvider.ANTHROPIC),
            "fal": key_service.resolve_key(APIProvider.FAL),
        }

        settings_service = get_settings_service(db)
        provider_config = settings_service.get_provider_config()

        return keys, provider_config
    except Exception as e:
        logger.warning(f"Failed to resolve config from DB: {e}")
        return {}, {}


def get_tagger(
    provider: Literal["openai", "anthropic"] | None = None,
    db: Session | None = None,
) -> BaseTagger:
    """Get tagger instance for the specified provider."""
    keys, config = _resolve_config(db)
    provider = provider or config.get("vision_provider") or settings.default_vision_provider
    if provider == "openai":
        return OpenAITagger(
            api_key=keys.get("openai"),
            model=config.get("openai_vision_model"),
        )
    elif provider == "anthropic":
        return AnthropicTagger(
            api_key=keys.get("anthropic"),
            model=config.get("anthropic_vision_model"),
        )
    else:
        raise ValueError(f"Unknown tagger provider: {provider}")


def get_describer(
    provider: Literal["openai", "anthropic"] | None = None,
    db: Session | None = None,
) -> BaseDescriber:
    """Get describer instance for the specified provider."""
    keys, config = _resolve_config(db)
    provider = provider or config.get("vision_provider") or settings.default_vision_provider
    if provider == "openai":
        return OpenAIDescriber(
            api_key=keys.get("openai"),
            model=config.get("openai_vision_model"),
        )
    elif provider == "anthropic":
        return AnthropicDescriber(
            api_key=keys.get("anthropic"),
            model=config.get("anthropic_vision_model"),
        )
    else:
        raise ValueError(f"Unknown describer provider: {provider}")


def get_embedder(
    provider: Literal["openai", "local"] | None = None,
    db: Session | None = None,
) -> BaseEmbedder:
    """Get embedder instance for the specified provider."""
    keys, config = _resolve_config(db)
    provider = provider or config.get("embedding_provider") or settings.default_embedding_provider
    if provider == "openai":
        return OpenAIEmbedder(
            api_key=keys.get("openai"),
            model=config.get("openai_embedding_model"),
        )
    else:
        raise ValueError(f"Unknown embedder provider: {provider}")


def get_cluster_summarizer(
    provider: Literal["openai", "anthropic"] | None = None,
    db: Session | None = None,
) -> BaseClusterSummarizer:
    """Get cluster summarizer instance for the specified provider."""
    keys, config = _resolve_config(db)
    provider = provider or config.get("vision_provider") or settings.default_vision_provider
    if provider == "openai":
        return OpenAIClusterSummarizer(
            api_key=keys.get("openai"),
            model=config.get("openai_vision_model"),
        )
    elif provider == "anthropic":
        return AnthropicClusterSummarizer(
            api_key=keys.get("anthropic"),
            model=config.get("anthropic_vision_model"),
        )
    else:
        raise ValueError(f"Unknown cluster summarizer provider: {provider}")


def get_trainer(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    base_model: str = "flux-dev",
) -> BaseTrainer:
    """Get trainer instance for the specified provider."""
    keys, _ = _resolve_config(db)
    provider = provider or settings.default_training_provider
    if provider == "fal":
        return FalTrainer(api_key=keys.get("fal"), base_model=base_model)
    else:
        raise ValueError(f"Unknown trainer provider: {provider}")


def get_generator(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    base_model: str = "flux-dev",
) -> BaseGenerator:
    """Get generator instance for the specified provider."""
    keys, _ = _resolve_config(db)
    provider = provider or settings.default_generation_provider
    if provider == "fal":
        return FalGenerator(api_key=keys.get("fal"), base_model=base_model)
    else:
        raise ValueError(f"Unknown generator provider: {provider}")


__all__ = [
    "BaseTagger",
    "BaseDescriber",
    "BaseEmbedder",
    "BaseClusterSummarizer",
    "BaseTrainer",
    "BaseGenerator",
    "TaggingResult",
    "DescriptionResult",
    "EmbeddingResult",
    "ClusterSummaryResult",
    "TrainingResult",
    "GenerationResult",
    "get_tagger",
    "get_describer",
    "get_embedder",
    "get_cluster_summarizer",
    "get_trainer",
    "get_generator",
]
