"""Anthropic Claude provider implementation for tagging and captioning."""
import base64
import json
import logging
import re

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.providers.base import (
    BaseCaptioner,
    BaseClusterSummarizer,
    BaseTagger,
    CaptionResult,
    ClusterSummaryResult,
    TaggingResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()

TAGGING_PROMPT_VERSION = "v1.0.0"

TAGGING_PROMPT = """Analyze this design/inspiration image and return a JSON object with structured tags.

Return ONLY a valid JSON object (no other text) with these exact keys. Each value should be an array of relevant tags (lowercase, hyphenated for multi-word).

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

Only include tags that are clearly present or relevant. Leave arrays empty if a category doesn't apply."""

CAPTION_PROMPT = """Analyze this design/inspiration image and provide:

1. **caption_short**: A single sentence (max 20 words) describing what's shown. Plain language.

2. **description_long**: 3-6 bullet points focusing on design-relevant observations:
   - Composition and layout
   - Color palette and relationships
   - Materials and textures visible
   - Lighting quality and direction
   - Typography if present
   - Overall mood/aesthetic
   - Potential use cases

Format as markdown bullets. Be specific and observational.

Return ONLY a valid JSON object (no other text):
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
1. **summary_title**: A concise title (3-7 words) capturing the essence of this group.

2. **summary_description**: 2-4 bullet points describing the unifying visual style, common elements, and what makes this group distinctive.

Return ONLY a valid JSON object (no other text):
{{
  "summary_title": "...",
  "summary_description": "- bullet 1\\n- bullet 2\\n..."
}}"""


def extract_json(text: str) -> dict:
    """Extract JSON from text that might have other content."""
    # Try to find JSON in the text
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {}


class AnthropicTagger(BaseTagger):
    """Anthropic Claude vision-based image tagger."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def tag_image(self, image_data: bytes, mime_type: str) -> TaggingResult:
        """Tag an image using Anthropic Claude."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        # Map MIME type to Anthropic's expected format
        media_type = mime_type
        if media_type == "image/jpg":
            media_type = "image/jpeg"

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_image,
                            },
                        },
                        {"type": "text", "text": TAGGING_PROMPT},
                    ],
                }
            ],
        )

        content = response.content[0].text if response.content else ""
        tags = extract_json(content)
        cleaned_tags = self._clean_tags(tags)

        return TaggingResult(
            tags=cleaned_tags,
            model=self.model,
            prompt_version=TAGGING_PROMPT_VERSION,
            raw_response={"content": content, "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}},
        )

    def _clean_tags(self, tags: dict) -> dict[str, list[str]]:
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


class AnthropicCaptioner(BaseCaptioner):
    """Anthropic Claude vision-based image captioner."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def caption_image(self, image_data: bytes, mime_type: str) -> CaptionResult:
        """Generate caption and description for an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        media_type = mime_type
        if media_type == "image/jpg":
            media_type = "image/jpeg"

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1500,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64_image,
                            },
                        },
                        {"type": "text", "text": CAPTION_PROMPT},
                    ],
                }
            ],
        )

        content = response.content[0].text if response.content else ""
        result = extract_json(content)

        return CaptionResult(
            caption_short=result.get("caption_short", ""),
            description_long=result.get("description_long", ""),
            model=self.model,
            raw_response={"content": content},
        )

    def get_model_name(self) -> str:
        return self.model


class AnthropicClusterSummarizer(BaseClusterSummarizer):
    """Anthropic Claude-based cluster summarizer."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_vision_model

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

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )

        content = response.content[0].text if response.content else ""
        result = extract_json(content)

        return ClusterSummaryResult(
            summary_title=result.get("summary_title", "Untitled Cluster"),
            summary_description=result.get("summary_description", ""),
            model=self.model,
        )

    def get_model_name(self) -> str:
        return self.model
