"""OpenAI provider implementation for tagging, captioning, and embedding."""
import base64
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
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

logger = logging.getLogger(__name__)
settings = get_settings()

# Prompt version for reproducibility
TAGGING_PROMPT_VERSION = "v1.0.0"
CAPTION_PROMPT_VERSION = "v1.0.0"

TAGGING_PROMPT = """Analyze this design/inspiration image and return a JSON object with structured tags.

Return ONLY a valid JSON object with these exact keys. Each value should be an array of relevant tags (lowercase, hyphenated for multi-word).

{
  "style": ["minimal", "editorial", "brutalist", "organic", "geometric", "vintage", "modern", "luxurious", "playful", "industrial"],
  "subject": ["portrait", "landscape", "product", "interior", "architecture", "food", "fashion", "abstract", "typography", "pattern"],
  "medium": ["photo", "3d-render", "illustration", "collage", "painting", "vector", "mixed-media", "digital-art"],
  "mood": ["calm", "energetic", "premium", "cozy", "dramatic", "whimsical", "serious", "dreamy", "bold"],
  "color_palette": ["warm", "cool", "neutral", "vibrant", "muted", "monochrome", "pastel", "earth-tones", "high-contrast"],
  "lighting": ["natural", "studio", "soft", "harsh", "dramatic", "ambient", "backlit", "golden-hour"],
  "materials": ["wood", "metal", "glass", "fabric", "paper", "concrete", "ceramic", "leather", "natural-fibers"],
  "composition": ["centered", "rule-of-thirds", "symmetrical", "asymmetrical", "negative-space", "layered", "grid", "diagonal"],
  "typography": ["none", "serif", "sans-serif", "script", "display", "hand-lettered", "mixed"],
  "era_reference": ["contemporary", "retro", "mid-century", "art-deco", "victorian", "futuristic", "timeless"]
}

Only include tags that are clearly present or relevant. Leave arrays empty if a category doesn't apply. Be consistent with the controlled vocabulary above."""

CAPTION_PROMPT = """Analyze this design/inspiration image and provide:

1. **caption_short**: A single sentence (max 20 words) describing what's shown. Plain language, no marketing speak.

2. **description_long**: 3-6 bullet points focusing on design-relevant observations:
   - Composition and layout
   - Color palette and relationships
   - Materials and textures visible
   - Lighting quality and direction
   - Typography if present
   - Overall mood/aesthetic
   - Potential use cases (web, print, branding, etc.)

Format the description as markdown bullet points. Be specific and observational rather than interpretive. Use consistent design vocabulary.

Return as JSON:
{
  "caption_short": "...",
  "description_long": "- bullet 1\\n- bullet 2\\n..."
}"""

CLUSTER_SUMMARY_PROMPT = """You're summarizing a cluster of {size} similar design inspiration images.

Common tags in this cluster:
{tags}

Sample descriptions from images in this cluster:
{descriptions}

Create:
1. **summary_title**: A concise title (3-7 words) capturing the essence of this group. Use design terminology. Examples: "Minimalist Product Photography, Warm Tones", "Bold Editorial Typography, High Contrast"

2. **summary_description**: 2-4 bullet points describing:
   - The unifying visual style/aesthetic
   - Common elements or techniques
   - Typical use cases or applications
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
    async def tag_image(self, image_data: bytes, mime_type: str) -> TaggingResult:
        """Tag an image using OpenAI vision model."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TAGGING_PROMPT},
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

        content = response.choices[0].message.content
        tags = json.loads(content) if content else {}

        # Clean and validate tags
        cleaned_tags = self._clean_tags(tags)

        return TaggingResult(
            tags=cleaned_tags,
            model=self.model,
            prompt_version=TAGGING_PROMPT_VERSION,
            raw_response={"content": content, "usage": response.usage.model_dump() if response.usage else None},
        )

    def _clean_tags(self, tags: dict[str, Any]) -> dict[str, list[str]]:
        """Clean and validate tags structure."""
        expected_keys = [
            "style", "subject", "medium", "mood", "color_palette",
            "lighting", "materials", "composition", "typography", "era_reference"
        ]
        cleaned = {}
        for key in expected_keys:
            value = tags.get(key, [])
            if isinstance(value, list):
                cleaned[key] = [str(v).lower().strip() for v in value if v]
            elif isinstance(value, str):
                cleaned[key] = [value.lower().strip()] if value else []
            else:
                cleaned[key] = []
        return cleaned

    def get_model_name(self) -> str:
        return self.model


class OpenAICaptioner(BaseCaptioner):
    """OpenAI vision-based image captioner."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def caption_image(self, image_data: bytes, mime_type: str) -> CaptionResult:
        """Generate caption and description for an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": CAPTION_PROMPT},
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
            max_tokens=1500,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        result = json.loads(content) if content else {}

        return CaptionResult(
            caption_short=result.get("caption_short", ""),
            description_long=result.get("description_long", ""),
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
        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )

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
        common_tags: dict[str, list[str]],
        sample_descriptions: list[str],
        cluster_size: int,
    ) -> ClusterSummaryResult:
        """Generate summary for a cluster of images."""
        tags_str = "\n".join(
            f"- {category}: {', '.join(tags)}"
            for category, tags in common_tags.items()
            if tags
        )
        descriptions_str = "\n\n".join(
            f"Image {i+1}:\n{desc}"
            for i, desc in enumerate(sample_descriptions[:5])
        )

        prompt = CLUSTER_SUMMARY_PROMPT.format(
            size=cluster_size,
            tags=tags_str,
            descriptions=descriptions_str,
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        result = json.loads(content) if content else {}

        return ClusterSummaryResult(
            summary_title=result.get("summary_title", "Untitled Cluster"),
            summary_description=result.get("summary_description", ""),
            model=self.model,
        )

    def get_model_name(self) -> str:
        return self.model
