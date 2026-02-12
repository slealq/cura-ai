"""Base interfaces for AI providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class AIContentError(Exception):
    """Raised when the AI model refuses or cannot process the image.

    Contains the reason reported by the model in the JSON error field.
    """

    def __init__(self, reason: str, operation: str = "process"):
        self.reason = reason
        self.operation = operation
        super().__init__(f"AI could not {operation} image: {reason}")


@dataclass
class TaggingResult:
    """Result from image tagging."""

    tags: list[str]
    model: str
    prompt_version: str
    raw_response: dict[str, Any] | None = None


@dataclass
class DescriptionResult:
    """Result from image description."""

    description: str
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
    async def tag_image(
        self, image_data: bytes, mime_type: str, tag_prompt: str | None = None
    ) -> TaggingResult:
        """
        Tag an image with flat categorization tags.

        Args:
            image_data: Raw image bytes
            mime_type: Image MIME type (e.g., "image/jpeg")
            tag_prompt: Full prompt to use for tagging (if None, uses provider default)

        Returns:
            TaggingResult with flat list of tags
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the model identifier for versioning."""
        pass


class BaseDescriber(ABC):
    """Abstract base class for image description providers."""

    @abstractmethod
    async def describe_image(
        self, image_data: bytes, mime_type: str, description_prompt: str | None = None
    ) -> DescriptionResult:
        """
        Generate a detailed description for an image.

        Args:
            image_data: Raw image bytes
            mime_type: Image MIME type
            description_prompt: Full prompt to use for description (if None, uses provider default)

        Returns:
            DescriptionResult with detailed description
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
        common_tags: list[str],
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
