"""Anthropic Claude provider implementation for tagging and description."""
import base64
import json
import logging
import re
import time

from anthropic import AsyncAnthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.services.log_service import write_log
from app.providers.base import (
    BaseClusterSummarizer,
    BaseDescriber,
    BaseTagger,
    ClusterSummaryResult,
    DescriptionResult,
    TaggingResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()

TAGGING_PROMPT_VERSION = "v2.0.0"

TAGGING_PROMPT = """Analyze this image and return a JSON object with a flat list of tags for categorization purposes.

Return ONLY a valid JSON object (no other text) with a single key "tags" containing an array of relevant tags (lowercase, hyphenated for multi-word).

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

Return ONLY a valid JSON object (no other text):
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
    async def tag_image(
        self, image_data: bytes, mime_type: str, tag_guidance: str | None = None
    ) -> TaggingResult:
        """Tag an image using Anthropic Claude."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        # Map MIME type to Anthropic's expected format
        media_type = mime_type
        if media_type == "image/jpg":
            media_type = "image/jpeg"

        # Build prompt with optional guidance
        prompt = TAGGING_PROMPT
        if tag_guidance:
            prompt = f"{prompt}\n\nAdditional guidance: {tag_guidance}\n\nPlease incorporate this guidance when selecting tags."

        start = time.monotonic()
        try:
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
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic tagging completed ({self.model})",
                provider="anthropic", model=self.model, operation="tag",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic tagging failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        content = response.content[0].text if response.content else ""
        result = extract_json(content)
        cleaned_tags = self._clean_tags(result)

        return TaggingResult(
            tags=cleaned_tags,
            model=self.model,
            prompt_version=TAGGING_PROMPT_VERSION,
            raw_response={"content": content, "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}},
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


class AnthropicDescriber(BaseDescriber):
    """Anthropic Claude vision-based image describer."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def describe_image(
        self, image_data: bytes, mime_type: str, description_guidance: str | None = None
    ) -> DescriptionResult:
        """Generate a detailed description for an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        media_type = mime_type
        if media_type == "image/jpg":
            media_type = "image/jpeg"

        # Build prompt with optional guidance
        prompt = DESCRIPTION_PROMPT
        if description_guidance:
            prompt = f"{prompt}\n\nAdditional guidance: {description_guidance}\n\nPlease incorporate this guidance when generating the description."

        start = time.monotonic()
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=3000,
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
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic describe completed ({self.model})",
                provider="anthropic", model=self.model, operation="describe",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic describe failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        content = response.content[0].text if response.content else ""
        result = extract_json(content)

        return DescriptionResult(
            description=result.get("description", ""),
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
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic summarize completed ({self.model})",
                provider="anthropic", model=self.model, operation="summarize",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic summarize failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="summarize", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        content = response.content[0].text if response.content else ""
        result = extract_json(content)

        return ClusterSummaryResult(
            summary_title=result.get("summary_title", "Untitled Cluster"),
            summary_description=result.get("summary_description", ""),
            model=self.model,
        )

    def get_model_name(self) -> str:
        return self.model
