"""OpenAI provider implementation for tagging, description, and embedding."""
import base64
import json
import logging
import time
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.services.log_service import write_log
from app.providers.base import (
    BaseClusterSummarizer,
    BaseDescriber,
    BaseEmbedder,
    BaseTagger,
    ClusterSummaryResult,
    DescriptionResult,
    EmbeddingResult,
    TaggingResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Prompt version for reproducibility
TAGGING_PROMPT_VERSION = "v2.0.0"
DESCRIPTION_PROMPT_VERSION = "v2.0.0"

TAGGING_PROMPT = """Analyze this image and return a JSON object with a flat list of tags for categorization purposes.

Return ONLY a valid JSON object with a single key "tags" containing an array of relevant tags (lowercase, hyphenated for multi-word).

Tags should categorize the image across these dimensions:
- Framing: full-body, upper-body, lower-body, feet-close-up, face-close-up, hands-close-up, medium-shot, wide-shot
- People: single-woman, single-man, multiple-people, couple, group
- Clothing: nude, semi-nude, clothed, lingerie, swimwear, dress, casual, formal, heels, barefoot
- Body features: soles-visible, toenails-visible, fingernails-visible, tattoos, piercings
- Activity: standing, sitting, lying-down, walking, posing, kneeling, bending-over
- Setting: indoor, outdoor, studio, bedroom, bathroom, beach, nature, urban
- Content: portrait, candid, artistic, professional, selfie, mirror

Only include tags that are clearly present or relevant.

{
  "tags": ["tag-1", "tag-2", "tag-3"]
}"""

DESCRIPTION_PROMPT = """Analyze this image and provide a detailed description organized by sections. The goal is that if someone uses this description to generate an image via AI, the result should match the original image as closely as possible.

Sections to cover (include all that are relevant):

**Subject**: Person(s) - clothing, pose, position of hands and legs, action, body position and orientation.

**Face & Hair**: Hair style, color, length. Facial expression, makeup, notable features.

**Body Details**: Nails (fingers/toes) - colors, shape, length. Accessories, jewelry, tattoos.

**Camera**: Camera angle, distance, perspective relative to subject. Framing (close-up, medium shot, full body).

**Background**: Setting description, colors, objects, depth of field.

**Lighting**: Quality, direction, color temperature, shadows.

**Special Focus**: If the image emphasizes feet, describe feet in detail - toenails, nail colors, nail shapes, sole visibility, toe positioning. If adult content, describe what is visible, body positioning, and physical details explicitly.

Be specific, observational, and thorough. Write in plain descriptive language. The description should be long and detailed enough to reproduce the image.

Return as JSON:
{
  "description": "## Subject\\n...\\n\\n## Face & Hair\\n...\\n\\n## Camera\\n..."
}"""

CLUSTER_SUMMARY_PROMPT = """You're summarizing a cluster of {size} similar images.

Common tags in this cluster:
{tags}

Sample descriptions from images in this cluster:
{descriptions}

Create:
1. **summary_title**: A concise title (3-7 words) capturing the essence of this group.

2. **summary_description**: 2-4 bullet points describing:
   - The unifying visual style/content
   - Common elements or features
   - What makes this group distinctive

Return as JSON:
{{
  "summary_title": "...",
  "summary_description": "- bullet 1\\n- bullet 2\\n..."
}}"""


class OpenAITagger(BaseTagger):
    """OpenAI vision-based image tagger."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def tag_image(
        self, image_data: bytes, mime_type: str, tag_guidance: str | None = None
    ) -> TaggingResult:
        """Tag an image using OpenAI vision model."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        # Build prompt with optional guidance
        prompt = TAGGING_PROMPT
        if tag_guidance:
            prompt = f"{prompt}\n\nAdditional guidance: {tag_guidance}\n\nPlease incorporate this guidance when selecting tags."

        start = time.monotonic()
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{base64_image}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=1000,
                response_format={"type": "json_object"},
            )
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI tagging completed ({self.model})",
                provider="openai", model=self.model, operation="tag",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI tagging failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        content = response.choices[0].message.content
        result = json.loads(content) if content else {}

        # Clean and validate tags
        cleaned_tags = self._clean_tags(result)

        return TaggingResult(
            tags=cleaned_tags,
            model=self.model,
            prompt_version=TAGGING_PROMPT_VERSION,
            raw_response={"content": content, "usage": response.usage.model_dump() if response.usage else None},
        )

    def _clean_tags(self, raw: dict | list) -> list[str]:
        """Clean and validate tags into a flat list."""
        if isinstance(raw, dict):
            tags = raw.get("tags", [])
        elif isinstance(raw, list):
            tags = raw
        else:
            tags = []
        if not isinstance(tags, list):
            tags = []
        return [str(t).lower().strip() for t in tags if t]

    def get_model_name(self) -> str:
        return self.model


class OpenAIDescriber(BaseDescriber):
    """OpenAI vision-based image describer."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def describe_image(
        self, image_data: bytes, mime_type: str, description_guidance: str | None = None
    ) -> DescriptionResult:
        """Generate a detailed description for an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        # Build prompt with optional guidance
        prompt = DESCRIPTION_PROMPT
        if description_guidance:
            prompt = f"{prompt}\n\nAdditional guidance: {description_guidance}\n\nPlease incorporate this guidance when generating the description."

        start = time.monotonic()
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{base64_image}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
                max_tokens=3000,
                response_format={"type": "json_object"},
            )
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI describe completed ({self.model})",
                provider="openai", model=self.model, operation="describe",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI describe failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        content = response.choices[0].message.content
        result = json.loads(content) if content else {}

        return DescriptionResult(
            description=result.get("description", ""),
            model=self.model,
            raw_response={"content": content, "usage": response.usage.model_dump() if response.usage else None},
        )

    def get_model_name(self) -> str:
        return self.model


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI text embedding provider."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_embedding_model
        self._dimensions = 1536  # text-embedding-3-small default

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def embed_text(self, text: str) -> EmbeddingResult:
        """Generate embedding for text."""
        start = time.monotonic()
        try:
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI embed completed ({self.model})",
                provider="openai", model=self.model, operation="embed",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.total_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI embed failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="embed", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        return EmbeddingResult(
            embedding=response.data[0].embedding,
            model=self.model,
            dimensions=len(response.data[0].embedding),
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts."""
        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )

        return [
            EmbeddingResult(
                embedding=data.embedding,
                model=self.model,
                dimensions=len(data.embedding),
            )
            for data in response.data
        ]

    def get_model_name(self) -> str:
        return self.model

    def get_dimensions(self) -> int:
        return self._dimensions


class OpenAIClusterSummarizer(BaseClusterSummarizer):
    """OpenAI-based cluster summarizer."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def summarize_cluster(
        self,
        common_tags: list[str],
        sample_descriptions: list[str],
        cluster_size: int,
    ) -> ClusterSummaryResult:
        """Generate summary for a cluster of images."""
        tags_str = ", ".join(common_tags) if common_tags else "No common tags"
        descriptions_str = "\n\n".join(
            f"Image {i+1}:\n{desc}"
            for i, desc in enumerate(sample_descriptions[:5])
        )

        prompt = CLUSTER_SUMMARY_PROMPT.format(
            size=cluster_size,
            tags=tags_str,
            descriptions=descriptions_str,
        )

        start = time.monotonic()
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI summarize completed ({self.model})",
                provider="openai", model=self.model, operation="summarize",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI summarize failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="summarize", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        content = response.choices[0].message.content
        result = json.loads(content) if content else {}

        return ClusterSummaryResult(
            summary_title=result.get("summary_title", "Untitled Cluster"),
            summary_description=result.get("summary_description", ""),
            model=self.model,
        )

    def get_model_name(self) -> str:
        return self.model
