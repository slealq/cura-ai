"""OpenAI provider implementation for tagging, description, and embedding."""
import base64
import json
import logging
import time

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
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
from app.providers.tracing import provider_span
from app.services.log_service import write_log

logger = logging.getLogger(__name__)
settings = get_settings()


_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model: str) -> bool:
    """Return True for models that use internal reasoning tokens."""
    return any(model.startswith(p) for p in _REASONING_PREFIXES)


def _token_limit_param(model: str, limit: int) -> dict:
    """Return the correct token limit kwarg for the model.

    Newer OpenAI models (gpt-5*, gpt-4.1*, chatgpt-4o*) require
    ``max_completion_tokens`` instead of the legacy ``max_tokens``.

    Reasoning models (gpt-5*, o-series) burn invisible reasoning tokens
    inside the completion budget.  We add a 2x buffer so the visible
    output isn't starved (e.g. tag with limit=1000 becomes 2000, leaving
    room for ~1000 reasoning + 1000 visible).
    """
    if any(model.startswith(p) for p in ("gpt-5", "gpt-4.1", "chatgpt-4o")):
        effective = limit * 2 if _is_reasoning_model(model) else limit
        return {"max_completion_tokens": effective}
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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None, temperature: float | None = None):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model or settings.openai_vision_model
        self.token_limit = (max_tokens or {}).get("tag", 1000)
        self.temperature = temperature

    async def tag_image(
        self, image_data: bytes, mime_type: str, tag_prompt: str | None = None
    ) -> TaggingResult:
        """Tag an image using OpenAI vision model."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        if not tag_prompt:
            raise ValueError("tag_prompt is required (composed by task layer)")

        start = time.monotonic()
        try:
            with provider_span("openai", "tag", self.model) as span:
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
                    **({"temperature": self.temperature} if self.temperature is not None else {}),
                    response_format={"type": "json_object"},
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.completion_tokens)
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            logger.warning(
                "OPENAI_AUDIT [tag] model=%s elapsed=%.0fms\n"
                "  REQUEST: prompt_text_len=%d image_bytes=%d prompt_text=%.500s\n"
                "  RESPONSE_FULL: %s\n"
                "  USAGE_DETAIL: %s\n"
                "  ACTUAL: in=%s out=%s",
                self.model, elapsed,
                len(tag_prompt), len(image_data), tag_prompt,
                response.model_dump(),
                usage.model_dump() if usage else None,
                usage.prompt_tokens if usage else None,
                usage.completion_tokens if usage else None,
            )
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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None, temperature: float | None = None):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model or settings.openai_vision_model
        self.token_limit = (max_tokens or {}).get("describe", 3000)
        self.temperature = temperature

    async def describe_image(
        self, image_data: bytes, mime_type: str, description_prompt: str | None = None
    ) -> DescriptionResult:
        """Generate a detailed description for an image."""
        base64_image = base64.b64encode(image_data).decode("utf-8")

        if not description_prompt:
            raise ValueError("description_prompt is required (composed by task layer)")

        # Only request JSON response format when the prompt asks for JSON output.
        # Custom user prompts may not mention JSON, and OpenAI rejects json_object
        # format unless the messages contain the word "json".
        _use_json_fmt = "json" in description_prompt.lower()

        start = time.monotonic()
        try:
            with provider_span("openai", "describe", self.model) as span:
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
                    **({"temperature": self.temperature} if self.temperature is not None else {}),
                    **({"response_format": {"type": "json_object"}} if _use_json_fmt else {}),
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.completion_tokens)
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            logger.warning(
                "OPENAI_AUDIT [describe] model=%s elapsed=%.0fms\n"
                "  REQUEST: prompt_text_len=%d image_bytes=%d prompt_text=%.500s\n"
                "  RESPONSE_FULL: %s\n"
                "  USAGE_DETAIL: %s\n"
                "  ACTUAL: in=%s out=%s",
                self.model, elapsed,
                len(description_prompt), len(image_data), description_prompt,
                response.model_dump(),
                usage.model_dump() if usage else None,
                usage.prompt_tokens if usage else None,
                usage.completion_tokens if usage else None,
            )
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

        # Parse response: try JSON first (standard tag/describe prompts),
        # fall back to plain text (custom prompts that don't request JSON).
        try:
            result = json.loads(content) if content else {}
        except (json.JSONDecodeError, TypeError):
            result = {}

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
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model or settings.openai_embedding_model
        self._dimensions = 1536  # text-embedding-3-small default

    async def embed_text(self, text: str) -> EmbeddingResult:
        """Generate embedding for text."""
        start = time.monotonic()
        try:
            with provider_span("openai", "embed", self.model) as span:
                response = await self.client.embeddings.create(
                    model=self.model,
                    input=text,
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.total", response.usage.total_tokens)
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            logger.warning(
                "OPENAI_AUDIT [embed] model=%s elapsed=%.0fms\n"
                "  REQUEST: text_len=%d text=%.500s\n"
                "  RESPONSE_FULL: %s\n"
                "  USAGE_DETAIL: %s\n"
                "  ACTUAL: in=%s",
                self.model, elapsed,
                len(text), text,
                {k: v for k, v in response.model_dump().items() if k != "data"},  # skip embedding vector
                usage.model_dump() if usage else None,
                usage.total_tokens if usage else None,
            )
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

    async def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts."""
        with provider_span("openai", "embed_batch", self.model) as span:
            response = await self.client.embeddings.create(
                model=self.model,
                input=texts,
            )
            if span and hasattr(response, 'usage') and response.usage:
                span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                span.set_attribute("ai.tokens.total", response.usage.total_tokens)

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
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model or settings.openai_vision_model
        self.token_limit = (max_tokens or {}).get("summarize", 500)

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
            with provider_span("openai", "summarize_cluster", self.model) as span:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    **_token_limit_param(self.model, self.token_limit),
                    response_format={"type": "json_object"},
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.completion_tokens)
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


EVAL_PROMPT = """You are a STRICT evaluator assessing how well a LoRA-trained model reproduced a reference image.

You are given:
1. The ORIGINAL reference image (first image)
2. The GENERATED image from a LoRA model (second image)
3. The prompt used to generate the image

**Prompt used:** {prompt}

## Scoring Calibration (FOLLOW STRICTLY)

Score each dimension from 0 to 10 using these anchors:
- **0-1**: Completely different. No recognizable connection between the images.
- **2-3**: Vaguely similar concept only. Different subject, different style, different composition.
- **4-5**: Same general subject or concept but clearly different execution. Noticeable style, color, or composition differences. Most details don't match.
- **6**: Recognizably attempting the same scene but with significant differences. Multiple wrong details.
- **7**: Same scene and style with some visible differences in details, proportions, or textures.
- **8**: Very close match with only minor differences noticeable on careful inspection.
- **9**: Nearly identical. Only subtle pixel-level differences.
- **10**: Indistinguishable. Reserve ONLY for perfect reproductions.

Most LoRA-generated images should score between 3 and 7. Scores above 8 should be exceptionally rare.

## CRITICAL: Human Features Penalty

If the images contain human faces, bodies, or anatomy:
- ANY distortion in facial features (wrong proportions, asymmetry, extra/missing features) → subject_accuracy MUST be ≤ 4
- Different person identity (wrong face, different person) → subject_accuracy MUST be ≤ 3
- Anatomical errors (wrong number of fingers, distorted limbs, impossible poses) → detail_preservation MUST be ≤ 3
- Uncanny valley effects → overall MUST be penalized by at least 2 points

## Dimensions

- **style_fidelity**: Does the generated image match the visual style? Same color palette, lighting, artistic technique, mood, and rendering quality?
- **subject_accuracy**: Does it capture the EXACT same subject? Same person/object identity, composition, pose, and spatial arrangement? Not just "similar looking" — the SAME subject.
- **detail_preservation**: Are fine details correct? Textures, patterns, text, small objects, backgrounds, accessories. Every missing or wrong detail reduces this score.
- **overall**: Holistic assessment. This MUST NOT be higher than the lowest dimension score + 2. If any dimension is ≤ 3, overall CANNOT exceed 5.

## Assessment

Provide a 2-3 sentence assessment focused on what went WRONG. What specific details differ? What features are missing or distorted? Be critical, not generous.

Return ONLY valid JSON:
{{
  "style_fidelity": <number>,
  "subject_accuracy": <number>,
  "detail_preservation": <number>,
  "overall": <number>,
  "assessment": "<string>"
}}"""


CREATIVE_EVAL_PROMPT = """You are a STRICT image quality evaluator assessing a single generated image from a LoRA-trained model.

There is NO reference image. You are evaluating this image purely on its own quality and fidelity to the prompt.

**Prompt used to generate:** {prompt}

## Scoring Calibration (FOLLOW STRICTLY)

Score each dimension from 0 to 10:
- **0-1**: Completely broken. Unrecognizable or incoherent.
- **2-3**: Major quality issues. Significant artifacts, distortion, or incoherence.
- **4-5**: Below average. Multiple noticeable problems with realism or detail.
- **6**: Acceptable but clearly AI-generated. Some artifacts or unrealistic elements.
- **7**: Good quality with minor issues. Mostly realistic with a few tells.
- **8**: High quality. Very few artifacts, realistic details.
- **9**: Excellent. Nearly flawless quality.
- **10**: Perfect. Reserve ONLY for exceptional quality.

## CRITICAL: Realism and Anatomy

- ANY facial distortion, asymmetry, or uncanny valley = realism MUST be ≤ 4
- Wrong number of fingers, distorted limbs, impossible anatomy = detail_quality MUST be ≤ 3
- Garbled or nonsensical text/lettering = detail_quality penalty of at least -2
- Repetitive patterns, texture glitches, or melted/blurred areas = realism penalty

## Dimensions

- **realism**: How realistic and natural does the image look? Free from AI artifacts, distortions, uncanny valley effects?
- **prompt_adherence**: How well does the image match what was described? Are all described elements present and correct?
- **detail_quality**: Quality of fine details — textures, edges, small objects, backgrounds. Crisp and accurate or blurry/malformed?
- **overall**: Holistic quality. MUST NOT be higher than the lowest dimension score + 2.

## Assessment

Provide a 2-3 sentence assessment focused on issues. What artifacts? What's missing from the prompt? What looks unnatural? Be critical and harsh.

Return ONLY valid JSON:
{{
  "realism": <number>,
  "prompt_adherence": <number>,
  "detail_quality": <number>,
  "overall": <number>,
  "assessment": "<string>"
}}"""


ASSESSMENT_SUMMARY_PROMPT = """You are summarizing the results of a LoRA model evaluation.

The LoRA model "{model_name}" (trigger word: "{trigger_word}") was evaluated by generating images and comparing them against originals from the training set.

{creative_section}

## Individual Pair Assessments

{pair_assessments}

## Aggregate Scores
- Overall Score: {overall_score}
- Average Vision Score: {avg_vision}
- Average Embedding Similarity: {avg_embedding}

## Your Task

Write a concise 3-5 sentence evaluation summary that:
1. States the overall quality verdict (poor / below average / acceptable / good / excellent)
2. Identifies the MAIN patterns of failure — what consistently goes wrong?
3. Highlights any strengths if they exist
4. Gives a specific, actionable recommendation (e.g., "increase training steps", "reduce learning rate", "add more diverse training images")

Focus on patterns and what went wrong, not on restating individual scores. Be direct and critical.

Return ONLY valid JSON:
{{
  "summary": "<string>"
}}"""


CREATIVE_PROMPT_GENERATION = """You are generating creative image prompts for testing a LoRA model's generalization ability.

The LoRA model was trained with trigger word "{trigger_word}" on images described as:

{sample_descriptions}

Generate {count} new, creative prompts that:
1. MUST start with the trigger word "{trigger_word}"
2. Are INSPIRED by the training set but describe ENTIRELY NEW scenes, compositions, or scenarios not present in the originals
3. Test the model's ability to generalize beyond its training data
4. Cover different scenarios, environments, lighting conditions, or styles
5. Are detailed enough to produce specific images (2-3 sentences each)

Return ONLY valid JSON:
{{
  "prompts": ["<prompt1>", "<prompt2>", ...]
}}"""


class OpenAIEvaluator(BaseEvaluator):
    """OpenAI vision-based image pair evaluator."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model or settings.openai_vision_model

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
            with provider_span("openai", "evaluate_pair", self.model) as span:
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
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.completion_tokens)
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

    async def evaluate_single(
        self,
        image_data: bytes,
        mime_type: str,
        prompt_used: str,
    ) -> VisionEvalResult:
        """Evaluate a single generated image on quality (no reference comparison)."""
        b64_image = base64.b64encode(image_data).decode("utf-8")
        prompt = CREATIVE_EVAL_PROMPT.format(prompt=prompt_used)

        start = time.monotonic()
        try:
            with provider_span("openai", "evaluate_single", self.model) as span:
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
                                        "url": f"data:{mime_type};base64,{b64_image}",
                                        "detail": "high",
                                    },
                                },
                            ],
                        }
                    ],
                    **_token_limit_param(self.model, 1000),
                    response_format={"type": "json_object"},
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.completion_tokens)
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI creative evaluate completed ({self.model})",
                provider="openai", model=self.model, operation="evaluate_creative",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI creative evaluate failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="evaluate_creative", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = json.loads(content) if content else {}

        return VisionEvalResult(
            style_fidelity=float(result.get("realism", 0)),
            subject_accuracy=float(result.get("prompt_adherence", 0)),
            detail_preservation=float(result.get("detail_quality", 0)),
            overall=float(result.get("overall", 0)),
            assessment=result.get("assessment", ""),
            model=self.model,
            raw_response={"content": content, "usage": response.usage.model_dump() if response.usage else None},
        )

    async def summarize_assessments(
        self,
        model_name: str,
        trigger_word: str,
        pair_assessments: list[dict],
        overall_score: float | None,
        avg_vision: float | None,
        avg_embedding: float | None,
        creative_section: str = "",
    ) -> str:
        """Generate a cohesive AI summary from individual assessments."""
        assessments_text = "\n".join(
            f"Pair {i+1} (score {a.get('score', 'N/A')}): {a.get('assessment', 'N/A')}"
            for i, a in enumerate(pair_assessments)
        )
        prompt = ASSESSMENT_SUMMARY_PROMPT.format(
            model_name=model_name,
            trigger_word=trigger_word,
            pair_assessments=assessments_text or "No assessments available.",
            overall_score=f"{overall_score:.1f}" if overall_score is not None else "N/A",
            avg_vision=f"{avg_vision:.1f}" if avg_vision is not None else "N/A",
            avg_embedding=f"{avg_embedding:.1f}" if avg_embedding is not None else "N/A",
            creative_section=creative_section,
        )

        start = time.monotonic()
        try:
            with provider_span("openai", "summarize_assessments", self.model) as span:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    **_token_limit_param(self.model, 1000),
                    response_format={"type": "json_object"},
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.completion_tokens)
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI assessment summary completed ({self.model})",
                provider="openai", model=self.model, operation="summarize_eval",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI assessment summary failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="summarize_eval", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = json.loads(content) if content else {}
        return result.get("summary", "")

    async def generate_creative_prompts(
        self,
        trigger_word: str,
        sample_descriptions: list[str],
        count: int,
    ) -> list[str]:
        """Generate creative prompts inspired by training set descriptions."""
        descriptions_text = "\n".join(
            f"- {desc[:300]}" for desc in sample_descriptions[:10]
        )
        prompt = CREATIVE_PROMPT_GENERATION.format(
            trigger_word=trigger_word,
            sample_descriptions=descriptions_text,
            count=count,
        )

        start = time.monotonic()
        try:
            with provider_span("openai", "generate_creative_prompts", self.model) as span:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    **_token_limit_param(self.model, 2000),
                    response_format={"type": "json_object"},
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.prompt_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.completion_tokens)
            elapsed = (time.monotonic() - start) * 1000
            usage = response.usage
            content = response.choices[0].message.content
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI creative prompt generation completed ({self.model})",
                provider="openai", model=self.model, operation="generate_prompts",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI creative prompt generation failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="generate_prompts", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = json.loads(content) if content else {}
        return result.get("prompts", [])[:count]

    def get_model_name(self) -> str:
        return self.model
