"""fal.ai OpenRouter vision provider for tagging, description, and evaluation."""
import base64
import json
import logging
import re
import time

import fal_client

from app.models.pipeline_log import LogCategory, LogLevel
from app.providers.base import (
    AIContentError,
    BaseDescriber,
    BaseEvaluator,
    BaseTagger,
    DescriptionResult,
    TaggingResult,
    VisionEvalResult,
)
from app.providers.fal_provider import _ensure_fal_key
from app.providers.tracing import provider_span
from app.services.log_service import write_log

logger = logging.getLogger(__name__)

TAGGING_PROMPT_VERSION = "v3.0.0"

FAL_OPENROUTER_ENDPOINT = "openrouter/router/vision"
DEFAULT_FAL_VISION_MODEL = "x-ai/grok-4-fast"

# Default polling interval for vision requests (seconds).
# fal_client.subscribe() defaults to ~200ms which floods the API.
_VISION_POLL_INTERVAL = 1.0


def _fal_submit_and_poll(endpoint: str, arguments: dict, poll_interval: float = _VISION_POLL_INTERVAL) -> dict:
    """Submit a fal.ai request and poll for completion at a sane interval."""
    from fal_client.client import Completed

    handle = fal_client.submit(endpoint, arguments=arguments)
    while True:
        status = handle.status(with_logs=False)
        if isinstance(status, Completed):
            break
        time.sleep(poll_interval)
    return handle.get()


def _extract_json(text: str) -> dict:
    """Extract JSON from text that might have other content."""
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    return {}


def _to_data_uri(image_data: bytes, mime_type: str) -> str:
    """Convert image bytes to a base64 data URI."""
    if mime_type == "image/jpg":
        mime_type = "image/jpeg"
    b64 = base64.b64encode(image_data).decode("utf-8")
    return f"data:{mime_type};base64,{b64}"


class FalVisionTagger(BaseTagger):
    """fal.ai OpenRouter vision-based image tagger."""

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None, temperature: float | None = None):
        _ensure_fal_key(api_key)
        self.model = model or DEFAULT_FAL_VISION_MODEL
        self.token_limit = (max_tokens or {}).get("tag", 1000)
        self.temperature = temperature

    async def tag_image(
        self, image_data: bytes, mime_type: str, tag_prompt: str | None = None
    ) -> TaggingResult:
        """Tag an image using fal.ai OpenRouter vision."""
        if not tag_prompt:
            raise ValueError("tag_prompt is required (composed by task layer)")

        data_uri = _to_data_uri(image_data, mime_type)

        args = {
            "image_urls": [data_uri],
            "prompt": tag_prompt,
            "model": self.model,
            "max_tokens": self.token_limit,
        }
        if self.temperature is not None:
            args["temperature"] = self.temperature

        start = time.monotonic()
        try:
            with provider_span("fal_vision", "tag", self.model) as span:
                result = _fal_submit_and_poll(
                    FAL_OPENROUTER_ENDPOINT,
                    arguments=args,
                )
                usage = result.get("usage", {})
                if span and usage:
                    input_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                    output_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                    if input_tok is not None:
                        span.set_attribute("ai.tokens.input", input_tok)
                    if output_tok is not None:
                        span.set_attribute("ai.tokens.output", output_tok)
            elapsed = (time.monotonic() - start) * 1000
            content = result.get("output", "")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter tagging completed ({self.model})",
                provider="fal", model=self.model, operation="tag",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
                provider_cost=usage.get("cost"),
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
                message=f"fal.ai OpenRouter tagging failed: {e}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e), "request_prompt": tag_prompt},
            )
            raise

        parsed = _extract_json(content)

        # Check for AI-reported error
        if "error" in parsed and not parsed.get("tags"):
            error = AIContentError(parsed["error"], operation="tag")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter tagging refused: {parsed['error']}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="tag", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(error), "ai_reason": parsed["error"], "response_content": content},
            )
            raise error

        cleaned_tags = self._clean_tags(parsed)

        return TaggingResult(
            tags=cleaned_tags,
            model=self.model,
            prompt_version=TAGGING_PROMPT_VERSION,
            raw_response={"content": content, "usage": usage},
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


class FalVisionDescriber(BaseDescriber):
    """fal.ai OpenRouter vision-based image describer."""

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None, temperature: float | None = None):
        _ensure_fal_key(api_key)
        self.model = model or DEFAULT_FAL_VISION_MODEL
        self.token_limit = (max_tokens or {}).get("describe", 3000)
        self.temperature = temperature

    async def describe_image(
        self, image_data: bytes, mime_type: str, description_prompt: str | None = None
    ) -> DescriptionResult:
        """Generate a detailed description using fal.ai OpenRouter vision."""
        if not description_prompt:
            raise ValueError("description_prompt is required (composed by task layer)")

        data_uri = _to_data_uri(image_data, mime_type)

        args = {
            "image_urls": [data_uri],
            "prompt": description_prompt,
            "model": self.model,
            "max_tokens": self.token_limit,
        }
        if self.temperature is not None:
            args["temperature"] = self.temperature

        start = time.monotonic()
        try:
            with provider_span("fal_vision", "describe", self.model) as span:
                result = _fal_submit_and_poll(
                    FAL_OPENROUTER_ENDPOINT,
                    arguments=args,
                )
                usage = result.get("usage", {})
                if span and usage:
                    input_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                    output_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                    if input_tok is not None:
                        span.set_attribute("ai.tokens.input", input_tok)
                    if output_tok is not None:
                        span.set_attribute("ai.tokens.output", output_tok)
            elapsed = (time.monotonic() - start) * 1000
            content = result.get("output", "")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter describe completed ({self.model})",
                provider="fal", model=self.model, operation="describe",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
                provider_cost=usage.get("cost"),
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
                message=f"fal.ai OpenRouter describe failed: {e}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e), "request_prompt": description_prompt},
            )
            raise

        parsed = _extract_json(content)

        # Check for AI-reported error
        if "error" in parsed and not parsed.get("description"):
            error = AIContentError(parsed["error"], operation="describe")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter describe refused: {parsed['error']}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="describe", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(error), "ai_reason": parsed["error"], "response_content": content},
            )
            raise error

        return DescriptionResult(
            description=parsed.get("description", ""),
            model=self.model,
            raw_response={"content": content},
        )

    def get_model_name(self) -> str:
        return self.model


# Import eval prompt constants from anthropic_provider
from app.providers.anthropic_provider import (  # noqa: E402
    ASSESSMENT_SUMMARY_PROMPT,
    CREATIVE_EVAL_PROMPT,
    CREATIVE_PROMPT_GENERATION,
    EVAL_PROMPT,
)


class FalVisionEvaluator(BaseEvaluator):
    """fal.ai OpenRouter vision-based image pair evaluator."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        _ensure_fal_key(api_key)
        self.model = model or DEFAULT_FAL_VISION_MODEL

    async def evaluate_pair(
        self,
        original_image_data: bytes,
        generated_image_data: bytes,
        original_mime: str,
        generated_mime: str,
        prompt_used: str,
    ) -> VisionEvalResult:
        """Compare original and generated images using fal.ai OpenRouter vision."""
        orig_uri = _to_data_uri(original_image_data, original_mime)
        gen_uri = _to_data_uri(generated_image_data, generated_mime)
        prompt = EVAL_PROMPT.format(prompt=prompt_used)

        start = time.monotonic()
        try:
            with provider_span("fal_vision", "evaluate_pair", self.model) as span:
                result = _fal_submit_and_poll(
                    FAL_OPENROUTER_ENDPOINT,
                    arguments={
                        "image_urls": [orig_uri, gen_uri],
                        "prompt": prompt,
                        "model": self.model,
                        "max_tokens": 1000,
                    },
                )
                usage = result.get("usage", {})
                if span and usage:
                    input_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                    output_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                    if input_tok is not None:
                        span.set_attribute("ai.tokens.input", input_tok)
                    if output_tok is not None:
                        span.set_attribute("ai.tokens.output", output_tok)
            elapsed = (time.monotonic() - start) * 1000
            content = result.get("output", "")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter evaluate completed ({self.model})",
                provider="fal", model=self.model, operation="evaluate",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
                provider_cost=usage.get("cost"),
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter evaluate failed: {e}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="evaluate", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        parsed = _extract_json(content)

        return VisionEvalResult(
            style_fidelity=float(parsed.get("style_fidelity", 0)),
            subject_accuracy=float(parsed.get("subject_accuracy", 0)),
            detail_preservation=float(parsed.get("detail_preservation", 0)),
            overall=float(parsed.get("overall", 0)),
            assessment=parsed.get("assessment", ""),
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
        data_uri = _to_data_uri(image_data, mime_type)
        prompt = CREATIVE_EVAL_PROMPT.format(prompt=prompt_used)

        start = time.monotonic()
        try:
            with provider_span("fal_vision", "evaluate_single", self.model) as span:
                result = _fal_submit_and_poll(
                    FAL_OPENROUTER_ENDPOINT,
                    arguments={
                        "image_urls": [data_uri],
                        "prompt": prompt,
                        "model": self.model,
                        "max_tokens": 1000,
                    },
                )
                usage = result.get("usage", {})
                if span and usage:
                    input_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                    output_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                    if input_tok is not None:
                        span.set_attribute("ai.tokens.input", input_tok)
                    if output_tok is not None:
                        span.set_attribute("ai.tokens.output", output_tok)
            elapsed = (time.monotonic() - start) * 1000
            content = result.get("output", "")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter creative evaluate completed ({self.model})",
                provider="fal", model=self.model, operation="evaluate_creative",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
                provider_cost=usage.get("cost"),
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter creative evaluate failed: {e}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="evaluate_creative", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        parsed = _extract_json(content)

        return VisionEvalResult(
            style_fidelity=float(parsed.get("realism", 0)),
            subject_accuracy=float(parsed.get("prompt_adherence", 0)),
            detail_preservation=float(parsed.get("detail_quality", 0)),
            overall=float(parsed.get("overall", 0)),
            assessment=parsed.get("assessment", ""),
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
            with provider_span("fal_vision", "summarize_assessments", self.model) as span:
                result = _fal_submit_and_poll(
                    FAL_OPENROUTER_ENDPOINT,
                    arguments={
                        "prompt": prompt,
                        "model": self.model,
                        "max_tokens": 1000,
                    },
                )
                usage = result.get("usage", {})
                if span and usage:
                    input_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                    output_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                    if input_tok is not None:
                        span.set_attribute("ai.tokens.input", input_tok)
                    if output_tok is not None:
                        span.set_attribute("ai.tokens.output", output_tok)
            elapsed = (time.monotonic() - start) * 1000
            content = result.get("output", "")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter assessment summary completed ({self.model})",
                provider="fal", model=self.model, operation="summarize_eval",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
                provider_cost=usage.get("cost"),
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter assessment summary failed: {e}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="summarize_eval", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        parsed = _extract_json(content)
        return parsed.get("summary", "")

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
            with provider_span("fal_vision", "generate_creative_prompts", self.model) as span:
                result = _fal_submit_and_poll(
                    FAL_OPENROUTER_ENDPOINT,
                    arguments={
                        "prompt": prompt,
                        "model": self.model,
                        "max_tokens": 2000,
                    },
                )
                usage = result.get("usage", {})
                if span and usage:
                    input_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                    output_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                    if input_tok is not None:
                        span.set_attribute("ai.tokens.input", input_tok)
                    if output_tok is not None:
                        span.set_attribute("ai.tokens.output", output_tok)
            elapsed = (time.monotonic() - start) * 1000
            content = result.get("output", "")
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter creative prompt generation completed ({self.model})",
                provider="fal", model=self.model, operation="generate_prompts",
                duration_ms=round(elapsed, 1),
                input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
                output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
                provider_cost=usage.get("cost"),
                success=True,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"fal.ai OpenRouter creative prompt generation failed: {e}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="generate_prompts", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        parsed = _extract_json(content)
        return parsed.get("prompts", [])[:count]

    def get_model_name(self) -> str:
        return self.model
