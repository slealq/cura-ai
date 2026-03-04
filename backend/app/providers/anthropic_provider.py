"""Anthropic Claude provider implementation for tagging and description."""
import base64
import json
import logging
import re
import time

from anthropic import AsyncAnthropic

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers.base import (
    AIContentError,
    BaseClusterSummarizer,
    BaseDescriber,
    BaseEvaluator,
    BaseTagger,
    ClusterSummaryResult,
    DescriptionResult,
    TaggingResult,
    VisionEvalResult,
)
from app.providers.tracing import provider_span
from app.services.log_service import write_log

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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None, temperature: float | None = None):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model or settings.anthropic_vision_model
        self.token_limit = (max_tokens or {}).get("tag", 1000)
        self.temperature = min(temperature, 1.0) if temperature is not None else None

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
            with provider_span("anthropic", "tag", self.model) as span:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.token_limit,
                    **({"temperature": self.temperature} if self.temperature is not None else {}),
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
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.input_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.output_tokens)
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

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None, temperature: float | None = None):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model or settings.anthropic_vision_model
        self.token_limit = (max_tokens or {}).get("describe", 3000)
        self.temperature = min(temperature, 1.0) if temperature is not None else None

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
            with provider_span("anthropic", "describe", self.model) as span:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.token_limit,
                    **({"temperature": self.temperature} if self.temperature is not None else {}),
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
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.input_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.output_tokens)
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
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model or settings.anthropic_vision_model
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
            with provider_span("anthropic", "summarize_cluster", self.model) as span:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=self.token_limit,
                    messages=[{"role": "user", "content": prompt}],
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.input_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.output_tokens)
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

Return ONLY a valid JSON object (no other text):
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

Return ONLY a valid JSON object (no other text):
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

Return ONLY a valid JSON object (no other text):
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

Return ONLY a valid JSON object (no other text):
{{
  "prompts": ["<prompt1>", "<prompt2>", ...]
}}"""


class AnthropicEvaluator(BaseEvaluator):
    """Anthropic Claude vision-based image pair evaluator."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model or settings.anthropic_vision_model

    async def evaluate_pair(
        self,
        original_image_data: bytes,
        generated_image_data: bytes,
        original_mime: str,
        generated_mime: str,
        prompt_used: str,
    ) -> VisionEvalResult:
        """Compare original and generated images using Claude Vision."""
        b64_original = base64.b64encode(original_image_data).decode("utf-8")
        b64_generated = base64.b64encode(generated_image_data).decode("utf-8")

        orig_media = original_mime if original_mime != "image/jpg" else "image/jpeg"
        gen_media = generated_mime if generated_mime != "image/jpg" else "image/jpeg"

        prompt = EVAL_PROMPT.format(prompt=prompt_used)

        start = time.monotonic()
        try:
            with provider_span("anthropic", "evaluate_pair", self.model) as span:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": orig_media,
                                        "data": b64_original,
                                    },
                                },
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": gen_media,
                                        "data": b64_generated,
                                    },
                                },
                            ],
                        }
                    ],
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.input_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.output_tokens)
            elapsed = (time.monotonic() - start) * 1000
            content = response.content[0].text if response.content else ""
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic evaluate completed ({self.model})",
                provider="anthropic", model=self.model, operation="evaluate",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic evaluate failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="evaluate", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = extract_json(content)

        return VisionEvalResult(
            style_fidelity=float(result.get("style_fidelity", 0)),
            subject_accuracy=float(result.get("subject_accuracy", 0)),
            detail_preservation=float(result.get("detail_preservation", 0)),
            overall=float(result.get("overall", 0)),
            assessment=result.get("assessment", ""),
            model=self.model,
            raw_response={"content": content},
        )

    async def evaluate_single(
        self,
        image_data: bytes,
        mime_type: str,
        prompt_used: str,
    ) -> VisionEvalResult:
        """Evaluate a single generated image on quality (no reference comparison)."""
        b64_image = base64.b64encode(image_data).decode("utf-8")
        media_type = mime_type if mime_type != "image/jpg" else "image/jpeg"
        prompt = CREATIVE_EVAL_PROMPT.format(prompt=prompt_used)

        start = time.monotonic()
        try:
            with provider_span("anthropic", "evaluate_single", self.model) as span:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": media_type,
                                        "data": b64_image,
                                    },
                                },
                            ],
                        }
                    ],
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.input_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.output_tokens)
            elapsed = (time.monotonic() - start) * 1000
            content = response.content[0].text if response.content else ""
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic creative evaluate completed ({self.model})",
                provider="anthropic", model=self.model, operation="evaluate_creative",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic creative evaluate failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="evaluate_creative", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = extract_json(content)

        return VisionEvalResult(
            style_fidelity=float(result.get("realism", 0)),
            subject_accuracy=float(result.get("prompt_adherence", 0)),
            detail_preservation=float(result.get("detail_quality", 0)),
            overall=float(result.get("overall", 0)),
            assessment=result.get("assessment", ""),
            model=self.model,
            raw_response={"content": content},
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
            with provider_span("anthropic", "summarize_assessments", self.model) as span:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[{"role": "user", "content": prompt}],
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.input_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.output_tokens)
            elapsed = (time.monotonic() - start) * 1000
            content = response.content[0].text if response.content else ""
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic assessment summary completed ({self.model})",
                provider="anthropic", model=self.model, operation="summarize_eval",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic assessment summary failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="summarize_eval", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = extract_json(content)
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
            with provider_span("anthropic", "generate_creative_prompts", self.model) as span:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
                if span and hasattr(response, 'usage') and response.usage:
                    span.set_attribute("ai.tokens.input", response.usage.input_tokens)
                    span.set_attribute("ai.tokens.output", response.usage.output_tokens)
            elapsed = (time.monotonic() - start) * 1000
            content = response.content[0].text if response.content else ""
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic creative prompt generation completed ({self.model})",
                provider="anthropic", model=self.model, operation="generate_prompts",
                duration_ms=round(elapsed, 1),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"Anthropic creative prompt generation failed: {e}",
                level=LogLevel.ERROR, provider="anthropic", model=self.model,
                operation="generate_prompts", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        result = extract_json(content)
        return result.get("prompts", [])[:count]

    def get_model_name(self) -> str:
        return self.model
