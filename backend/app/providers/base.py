"""Base interfaces for AI providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class TaggingResult:
    """Result from image tagging."""

    tags: dict[str, list[str]]
    model: str
    prompt_version: str
    raw_response: dict[str, Any] | None = None


@dataclass
class CaptionResult:
    """Result from image captioning/description."""

    caption_short: str
    description_long: str  # Markdown bullet points
    model: str
    raw_response: dict[str, Any] | None = None


@dataclass
class EmbeddingResult:
    """Result from embedding generation."""

    embedding: list[float]
    model: str
    dimensions: int


@dataclass
class ClusterSummaryResult:
    """Result from cluster summarization."""

    summary_title: str
    summary_description: str  # Markdown bullet points
    model: str


class BaseTagger(ABC):
    """Abstract base class for image tagging providers."""

    @abstractmethod
    async def tag_image(self, image_data: bytes, mime_type: str) -> TaggingResult:
        """
        Tag an image with structured metadata.

        Args:
            image_data: Raw image bytes
            mime_type: Image MIME type (e.g., "image/jpeg")

        Returns:
            TaggingResult with structured tags
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model identifier for versioning."""
        pass


class BaseCaptioner(ABC):
    """Abstract base class for image captioning providers."""

    @abstractmethod
    async def caption_image(self, image_data: bytes, mime_type: str) -> CaptionResult:
        """
        Generate caption and description for an image.

        Args:
            image_data: Raw image bytes
            mime_type: Image MIME type

        Returns:
            CaptionResult with short caption and long description
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model identifier for versioning."""
        pass


class BaseEmbedder(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    async def embed_text(self, text: str) -> EmbeddingResult:
        """
        Generate embedding for text.

        Args:
            text: Text to embed (typically tags + description)

        Returns:
            EmbeddingResult with embedding vector
        """
        pass

    @abstractmethod
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of EmbeddingResult
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model identifier for versioning."""
        pass

    @abstractmethod
    def get_dimensions(self) -> int:
        """Get the embedding dimensions."""
        pass


class BaseClusterSummarizer(ABC):
    """Abstract base class for cluster summarization providers."""

    @abstractmethod
    async def summarize_cluster(
        self,
        common_tags: dict[str, list[str]],
        sample_descriptions: list[str],
        cluster_size: int,
    ) -> ClusterSummaryResult:
        """
        Generate summary for a cluster of images.

        Args:
            common_tags: Most frequent tags in the cluster
            sample_descriptions: Sample descriptions from cluster images
            cluster_size: Number of images in the cluster

        Returns:
            ClusterSummaryResult with title and description
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model identifier for versioning."""
        pass
