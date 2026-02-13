"""Anthropic Claude provider implementation for tagging and description."""
import base64
import json
import logging
import re
import time

from anthropic import AsyncAnthropic
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.services.log_service import write_log
from app.providers.base import (
    AIContentError,
    BaseClusterSummarizer,
    BaseDescriber,
    BaseTagger,
    ClusterSummaryResult,
    DescriptionResult,
    TaggingResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()

TAGGING_PROMPT_VERSION = "v3.0.0"

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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None):
        self.client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.anthropic_vision_model
        self.token_limit = (max_tokens or {}).get("tag", 1000)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_not_exception_type(AIContentError))
    async def tag_image(
        self, image_data: bytes, mime_type: str, tag_prompt: str | None = None
    ) -> TaggingResult:
        """Tag an image using Anthropic Claude."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        # Map MIME type to Anthropic's expected format
        media_type = mime_type
        if media_type == "image/jpg":
            media_type = "image/jpeg"

        if not tag_prompt:
            raise ValueError("tag_prompt is required (composed by task layer)")

        start = time.monotonic()
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.token_limit,
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
                            {"type": "text", "text": tag_prompt},
                        ],
                    }
                ],
            )
            elapsed = (time.monotonic() - start) * 1000
            content = response.content[0].text if response.content else ""
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic tagging completed ({self.model})",
                provider="anthropic", model=self.model, operation="tag",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
                extra={
                    "request_prompt": tag_prompt,
                    "response_content": content,
                },
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic tagging failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e), "request_prompt": tag_prompt},
            )
            raise
        result = extract_json(content)

        # Check for AI-reported error
        if "error" in result and not result.get("tags"):
            error = AIContentError(result["error"], operation="tag")
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic tagging refused: {result['error']}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(error), "ai_reason": result["error"], "response_content": content},
            )
            raise error

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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None):
        self.client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.anthropic_vision_model
        self.token_limit = (max_tokens or {}).get("describe", 3000)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_not_exception_type(AIContentError))
    async def describe_image(
        self, image_data: bytes, mime_type: str, description_prompt: str | None = None
    ) -> DescriptionResult:
        """Generate a detailed description for an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        media_type = mime_type
        if media_type == "image/jpg":
            media_type = "image/jpeg"

        if not description_prompt:
            raise ValueError("description_prompt is required (composed by task layer)")

        start = time.monotonic()
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=self.token_limit,
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
                            {"type": "text", "text": description_prompt},
                        ],
                    }
                ],
            )
            elapsed = (time.monotonic() - start) * 1000
            content = response.content[0].text if response.content else ""
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic describe completed ({self.model})",
                provider="anthropic", model=self.model, operation="describe",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
                extra={
                    "request_prompt": description_prompt,
                    "response_content": content,
                },
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic describe failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e), "request_prompt": description_prompt},
            )
            raise
        result = extract_json(content)

        # Check for AI-reported error
        if "error" in result and not result.get("description"):
            error = AIContentError(result["error"], operation="describe")
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic describe refused: {result['error']}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(error), "ai_reason": result["error"], "response_content": content},
            )
            raise error

        return DescriptionResult(
            description=result.get("description", ""),
            model=self.model,
            raw_response={"content": content},
        )

    def get_model_name(self) -> str:
        return self.model


class AnthropicClusterSummarizer(BaseClusterSummarizer):
    """Anthropic Claude-based cluster summarizer."""

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None):
        self.client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.anthropic_vision_model
        self.token_limit = (max_tokens or {}).get("summarize", 500)

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
                max_tokens=self.token_limit,
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
