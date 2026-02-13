"""OpenAI provider implementation for tagging, description, and embedding."""
import base64
import json
import logging
import time
from typing import Any

from openai import AsyncOpenAI
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.services.log_service import write_log
from app.providers.base import (
    AIContentError,
    BaseClusterSummarizer,
    BaseDescriber,
    BaseEmbedder,
    BaseEvaluator,
    BaseTagger,
    ClusterSummaryResult,
    DescriptionResult,
    EmbeddingResult,
    TaggingResult,
    VisionEvalResult,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _token_limit_param(model: str, limit: int) -> dict:
    """Return the correct token limit kwarg for the model.

    Newer OpenAI models (gpt-5*, gpt-4.1*, chatgpt-4o*) require
    ``max_completion_tokens`` instead of the legacy ``max_tokens``.
    """
    if any(model.startswith(p) for p in ("gpt-5", "gpt-4.1", "chatgpt-4o")):
        return {"max_completion_tokens": limit}
    return {"max_tokens": limit}

# Prompt version for reproducibility
TAGGING_PROMPT_VERSION = "v3.0.0"
DESCRIPTION_PROMPT_VERSION = "v3.0.0"

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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.openai_vision_model
        self.token_limit = (max_tokens or {}).get("tag", 1000)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_not_exception_type(AIContentError))
    async def tag_image(
        self, image_data: bytes, mime_type: str, tag_prompt: str | None = None
    ) -> TaggingResult:
        """Tag an image using OpenAI vision model."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        if not tag_prompt:
            raise ValueError("tag_prompt is required (composed by task layer)")

        start = time.monotonic()
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": tag_prompt},
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
                **_token_limit_param(self.model, self.token_limit),
                response_format={"type": "json_object"},
            )
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI tagging completed ({self.model})",
                provider="openai", model=self.model, operation="tag",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
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
                message=f"OpenAI tagging failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e), "request_prompt": tag_prompt},
            )
            raise
        result = json.loads(content) if content else {}

        # Check for AI-reported error
        if "error" in result and not result.get("tags"):
            error = AIContentError(result["error"], operation="tag")
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI tagging refused: {result['error']}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(error), "ai_reason": result["error"], "response_content": content},
            )
            raise error

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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.openai_vision_model
        self.token_limit = (max_tokens or {}).get("describe", 3000)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10),
           retry=retry_if_not_exception_type(AIContentError))
    async def describe_image(
        self, image_data: bytes, mime_type: str, description_prompt: str | None = None
    ) -> DescriptionResult:
        """Generate a detailed description for an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        if not description_prompt:
            raise ValueError("description_prompt is required (composed by task layer)")

        start = time.monotonic()
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": description_prompt},
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
                **_token_limit_param(self.model, self.token_limit),
                response_format={"type": "json_object"},
            )
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI describe completed ({self.model})",
                provider="openai", model=self.model, operation="describe",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
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
                message=f"OpenAI describe failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e), "request_prompt": description_prompt},
            )
            raise

        result = json.loads(content) if content else {}

        # Check for AI-reported error
        if "error" in result and not result.get("description"):
            error = AIContentError(result["error"], operation="describe")
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI describe refused: {result['error']}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(error), "ai_reason": result["error"], "response_content": content},
            )
            raise error

        description = result.get("description") or content or ""

        return DescriptionResult(
            description=description,
            model=self.model,
            raw_response={"content": content, "usage": response.usage.model_dump() if response.usage else None},
        )

    def get_model_name(self) -> str:
        return self.model


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI text embedding provider."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.openai_embedding_model
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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.openai_vision_model
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
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                **_token_limit_param(self.model, self.token_limit),
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


EVAL_PROMPT = """You are evaluating how well a LoRA-trained model reproduced a reference image.

You are given:
1. The ORIGINAL reference image (first image)
2. The GENERATED image from a LoRA model (second image)
3. The prompt used to generate the image

**Prompt used:** {prompt}

Score each dimension from 0 to 10 (0 = no resemblance, 10 = indistinguishable):

- **style_fidelity**: How well does the generated image match the visual style (color palette, lighting, artistic technique, mood) of the original?
- **subject_accuracy**: How well does the generated image capture the same subject, composition, and key elements?
- **detail_preservation**: How well are fine details, textures, and subtle features preserved?
- **overall**: Your holistic assessment combining all factors.

Also provide a 2-3 sentence **assessment** explaining the key similarities and differences.

Return ONLY valid JSON:
{{
  "style_fidelity": <number>,
  "subject_accuracy": <number>,
  "detail_preservation": <number>,
  "overall": <number>,
  "assessment": "<string>"
}}"""


class OpenAIEvaluator(BaseEvaluator):
    """OpenAI vision-based image pair evaluator."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.openai_vision_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def evaluate_pair(
        self,
        original_image_data: bytes,
        generated_image_data: bytes,
        original_mime: str,
        generated_mime: str,
        prompt_used: str,
    ) -> VisionEvalResult:
        """Compare original and generated images using GPT-4 Vision."""
        b64_original = base64.b64encode(original_image_data).decode("utf-8")
        b64_generated = base64.b64encode(generated_image_data).decode("utf-8")

        prompt = EVAL_PROMPT.format(prompt=prompt_used)

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
                                    "url": f"data:{original_mime};base64,{b64_original}",
                                    "detail": "high",
                                },
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{generated_mime};base64,{b64_generated}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
                **_token_limit_param(self.model, 1000),
                response_format={"type": "json_object"},
            )
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI evaluate completed ({self.model})",
                provider="openai", model=self.model, operation="evaluate",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI evaluate failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="evaluate", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = json.loads(content) if content else {}

        return VisionEvalResult(
            style_fidelity=float(result.get("style_fidelity", 0)),
            subject_accuracy=float(result.get("subject_accuracy", 0)),
            detail_preservation=float(result.get("detail_preservation", 0)),
            overall=float(result.get("overall", 0)),
            assessment=result.get("assessment", ""),
            model=self.model,
            raw_response={"content": content, "usage": response.usage.model_dump() if response.usage else None},
        )

    def get_model_name(self) -> str:
        return self.model
