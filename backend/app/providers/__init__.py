"""Provider factory for AI services."""
from typing import Literal

from app.core.config import get_settings
from app.providers.anthropic_provider import (
    AnthropicCaptioner,
    AnthropicClusterSummarizer,
    AnthropicTagger,
)
from app.providers.base import (
    BaseCaptioner,
    BaseClusterSummarizer,
    BaseEmbedder,
    BaseTagger,
    CaptionResult,
    ClusterSummaryResult,
    EmbeddingResult,
    TaggingResult,
)
from app.providers.openai_provider import (
    OpenAICaptioner,
    OpenAIClusterSummarizer,
    OpenAIEmbedder,
    OpenAITagger,
)

settings = get_settings()


def get_tagger(provider: Literal["openai", "anthropic"] | None = None) -> BaseTagger:
    """Get tagger instance for the specified provider."""
    provider = provider or settings.default_vision_provider
    if provider == "openai":
        return OpenAITagger()
    elif provider == "anthropic":
        return AnthropicTagger()
    else:
        raise ValueError(f"Unknown tagger provider: {provider}")


def get_captioner(provider: Literal["openai", "anthropic"] | None = None) -> BaseCaptioner:
    """Get captioner instance for the specified provider."""
    provider = provider or settings.default_vision_provider
    if provider == "openai":
        return OpenAICaptioner()
    elif provider == "anthropic":
        return AnthropicCaptioner()
    else:
        raise ValueError(f"Unknown captioner provider: {provider}")


def get_embedder(provider: Literal["openai", "local"] | None = None) -> BaseEmbedder:
    """Get embedder instance for the specified provider."""
    provider = provider or settings.default_embedding_provider
    if provider == "openai":
        return OpenAIEmbedder()
    else:
        raise ValueError(f"Unknown embedder provider: {provider}")


def get_cluster_summarizer(
    provider: Literal["openai", "anthropic"] | None = None
) -> BaseClusterSummarizer:
    """Get cluster summarizer instance for the specified provider."""
    provider = provider or settings.default_vision_provider
    if provider == "openai":
        return OpenAIClusterSummarizer()
    elif provider == "anthropic":
        return AnthropicClusterSummarizer()
    else:
        raise ValueError(f"Unknown cluster summarizer provider: {provider}")


__all__ = [
    "BaseTagger",
    "BaseCaptioner",
    "BaseEmbedder",
    "BaseClusterSummarizer",
    "TaggingResult",
    "CaptionResult",
    "EmbeddingResult",
    "ClusterSummaryResult",
    "get_tagger",
    "get_captioner",
    "get_embedder",
    "get_cluster_summarizer",
]
