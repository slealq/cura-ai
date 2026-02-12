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


@dataclass
class TrainingResult:
    """Result from LoRA training."""

    lora_url: str
    request_id: str
    provider: str
    metadata: dict[str, Any] | None = None


@dataclass
class GenerationResult:
    """Result from image generation."""

    image_data: bytes
    width: int
    height: int
    seed: int | None = None
    provider: str = ""
    metadata: dict[str, Any] | None = None


class BaseTrainer(ABC):
    """Abstract base class for LoRA training providers."""

    @abstractmethod
    async def start_training(
        self,
        image_urls: list[str],
        trigger_word: str,
        steps: int = 1000,
        is_style: bool = False,
        **kwargs: Any,
    ) -> str:
        """Start a LoRA training job. Returns request_id."""
        pass

    @abstractmethod
    async def check_training_status(self, request_id: str) -> dict[str, Any]:
        """Check training job status. Returns status dict."""
        pass

    @abstractmethod
    async def get_training_result(self, request_id: str) -> TrainingResult:
        """Get completed training result."""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the provider identifier."""
        pass


class BaseGenerator(ABC):
    """Abstract base class for image generation providers."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        negative_prompt: str | None = None,
        width: int = 1024,
        height: int = 1024,
        num_inference_steps: int = 28,
        guidance_scale: float = 3.5,
        seed: int | None = None,
        lora_url: str | None = None,
        lora_scale: float = 1.0,
    ) -> GenerationResult:
        """Generate an image. Returns GenerationResult with image bytes."""
        pass

    @abstractmethod
    def get_provider_name(self) -> str:
        """Get the provider identifier."""
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
