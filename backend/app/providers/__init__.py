"""Provider factory for AI services."""
import logging
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.providers.anthropic_provider import (
    AnthropicClusterSummarizer,
    AnthropicDescriber,
    AnthropicEvaluator,
    AnthropicTagger,
)
from app.providers.base import (
    BaseClusterSummarizer,
    BaseDescriber,
    BaseEditor,
    BaseEmbedder,
    BaseEvaluator,
    BaseGenerator,
    BaseTagger,
    BaseTrainer,
    ClusterSummaryResult,
    DescriptionResult,
    EditResult,
    EmbeddingResult,
    GenerationResult,
    TaggingResult,
    TrainingResult,
    VisionEvalResult,
)
from app.providers.fal_provider import FalEditor, FalGenerator, FalTrainer
from app.providers.fal_vision_provider import FalVisionDescriber, FalVisionEvaluator, FalVisionTagger
from app.providers.openai_provider import (
    OpenAIClusterSummarizer,
    OpenAIDescriber,
    OpenAIEmbedder,
    OpenAIEvaluator,
    OpenAITagger,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_config(db: Session | None, user_id: int | None = None):
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

        key_service = get_api_key_service(db, user_id) if user_id else None
        if key_service:
            keys = {
                "openai": key_service.resolve_key(APIProvider.OPENAI),
                "anthropic": key_service.resolve_key(APIProvider.ANTHROPIC),
                "fal": key_service.resolve_key(APIProvider.FAL),
            }
        else:
            # No user context — no keys available
            keys = {}

        settings_service = get_settings_service(db, user_id) if user_id else None
        provider_config = settings_service.get_provider_config() if settings_service else {}

        return keys, provider_config
    except Exception as e:
        logger.warning(f"Failed to resolve config from DB: {e}")
        return {}, {}


def _token_config(config: dict) -> dict:
    """Build token limits dict from provider config."""
    return {
        "tag": config.get("max_tokens_tagging", 1000),
        "describe": config.get("max_tokens_description", 3000),
        "summarize": config.get("max_tokens_summarization", 500),
    }


def get_tagger(
    provider: Literal["openai", "anthropic", "fal"] | None = None,
    db: Session | None = None,
    user_id: int | None = None,
    model: str | None = None,
) -> BaseTagger:
    """Get tagger instance for the specified provider."""
    keys, config = _resolve_config(db, user_id)
    max_tokens = _token_config(config)
    provider = provider or config.get("vision_provider") or settings.default_vision_provider
    if provider == "openai":
        return OpenAITagger(
            api_key=keys.get("openai"),
            model=model or config.get("openai_vision_model"),
            max_tokens=max_tokens,
        )
    elif provider == "anthropic":
        return AnthropicTagger(
            api_key=keys.get("anthropic"),
            model=model or config.get("anthropic_vision_model"),
            max_tokens=max_tokens,
        )
    elif provider == "fal":
        return FalVisionTagger(
            api_key=keys.get("fal"),
            model=model or config.get("fal_vision_model"),
            max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unknown tagger provider: {provider}")


def get_describer(
    provider: Literal["openai", "anthropic", "fal"] | None = None,
    db: Session | None = None,
    user_id: int | None = None,
    model: str | None = None,
) -> BaseDescriber:
    """Get describer instance for the specified provider."""
    keys, config = _resolve_config(db, user_id)
    max_tokens = _token_config(config)
    provider = provider or config.get("vision_provider") or settings.default_vision_provider
    if provider == "openai":
        return OpenAIDescriber(
            api_key=keys.get("openai"),
            model=model or config.get("openai_vision_model"),
            max_tokens=max_tokens,
        )
    elif provider == "anthropic":
        return AnthropicDescriber(
            api_key=keys.get("anthropic"),
            model=model or config.get("anthropic_vision_model"),
            max_tokens=max_tokens,
        )
    elif provider == "fal":
        return FalVisionDescriber(
            api_key=keys.get("fal"),
            model=model or config.get("fal_vision_model"),
            max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unknown describer provider: {provider}")


def get_embedder(
    provider: Literal["openai", "local"] | None = None,
    db: Session | None = None,
    user_id: int | None = None,
) -> BaseEmbedder:
    """Get embedder instance for the specified provider."""
    keys, config = _resolve_config(db, user_id)
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
    user_id: int | None = None,
) -> BaseClusterSummarizer:
    """Get cluster summarizer instance for the specified provider."""
    keys, config = _resolve_config(db, user_id)
    max_tokens = _token_config(config)
    provider = provider or config.get("vision_provider") or settings.default_vision_provider
    if provider == "openai":
        return OpenAIClusterSummarizer(
            api_key=keys.get("openai"),
            model=config.get("openai_vision_model"),
            max_tokens=max_tokens,
        )
    elif provider == "anthropic":
        return AnthropicClusterSummarizer(
            api_key=keys.get("anthropic"),
            model=config.get("anthropic_vision_model"),
            max_tokens=max_tokens,
        )
    else:
        raise ValueError(f"Unknown cluster summarizer provider: {provider}")


def get_trainer(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    base_model: str = "flux-dev",
    user_id: int | None = None,
) -> BaseTrainer:
    """Get trainer instance for the specified provider."""
    keys, _ = _resolve_config(db, user_id)
    provider = provider or settings.default_training_provider
    if provider == "fal":
        return FalTrainer(api_key=keys.get("fal"), base_model=base_model)
    else:
        raise ValueError(f"Unknown trainer provider: {provider}")


def get_generator(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    base_model: str = "flux-dev",
    user_id: int | None = None,
) -> BaseGenerator:
    """Get generator instance for the specified provider."""
    keys, _ = _resolve_config(db, user_id)
    provider = provider or settings.default_generation_provider
    if provider == "fal":
        return FalGenerator(api_key=keys.get("fal"), base_model=base_model)
    else:
        raise ValueError(f"Unknown generator provider: {provider}")


def get_editor(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    edit_model: str = "qwen-image-max-edit",
    user_id: int | None = None,
) -> BaseEditor:
    """Get editor instance for the specified provider."""
    keys, _ = _resolve_config(db, user_id)
    provider = provider or "fal"
    if provider == "fal":
        return FalEditor(api_key=keys.get("fal"), edit_model=edit_model)
    else:
        raise ValueError(f"Unknown editor provider: {provider}")


def get_evaluator(
    provider: Literal["openai", "anthropic", "fal"] | None = None,
    db: Session | None = None,
    user_id: int | None = None,
) -> BaseEvaluator:
    """Get evaluator instance for the specified provider."""
    keys, config = _resolve_config(db, user_id)
    provider = provider or config.get("vision_provider") or settings.default_vision_provider
    if provider == "openai":
        return OpenAIEvaluator(
            api_key=keys.get("openai"),
            model=config.get("openai_vision_model"),
        )
    elif provider == "anthropic":
        return AnthropicEvaluator(
            api_key=keys.get("anthropic"),
            model=config.get("anthropic_vision_model"),
        )
    elif provider == "fal":
        return FalVisionEvaluator(
            api_key=keys.get("fal"),
            model=config.get("fal_vision_model"),
        )
    else:
        raise ValueError(f"Unknown evaluator provider: {provider}")


__all__ = [
    "BaseTagger",
    "BaseDescriber",
    "BaseEditor",
    "BaseEmbedder",
    "BaseEvaluator",
    "BaseClusterSummarizer",
    "BaseTrainer",
    "BaseGenerator",
    "TaggingResult",
    "DescriptionResult",
    "EditResult",
    "EmbeddingResult",
    "ClusterSummaryResult",
    "TrainingResult",
    "GenerationResult",
    "VisionEvalResult",
    "get_tagger",
    "get_describer",
    "get_editor",
    "get_embedder",
    "get_cluster_summarizer",
    "get_trainer",
    "get_generator",
    "get_evaluator",
]
