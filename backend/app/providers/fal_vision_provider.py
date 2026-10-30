"""fal.ai OpenRouter provider for vision and language operations.

Every call goes through :func:`build_router_request`, which picks the router
endpoint (vision when images are attached, text-only otherwise) and drops
``temperature`` for models that reject it.
"""
import asyncio
import base64
import json
import logging
import re
import time
from dataclasses import dataclass

import fal_client

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
from app.providers.fal_provider import _ensure_fal_key
from app.providers.prompts import (
    ASSESSMENT_SUMMARY_PROMPT,
    CLUSTER_SUMMARY_PROMPT,
    CREATIVE_EVAL_PROMPT,
    CREATIVE_PROMPT_GENERATION,
    EVAL_PROMPT,
)
from app.providers.tracing import provider_span
from app.services.log_service import write_log
from app.services.model_catalog import DEFAULT_VISION_MODEL, get_language_model

logger = logging.getLogger(__name__)

TAGGING_PROMPT_VERSION = "v3.0.0"

FAL_ROUTER_ENDPOINT = "openrouter/router"
FAL_VISION_ENDPOINT = "openrouter/router/vision"
DEFAULT_FAL_VISION_MODEL = DEFAULT_VISION_MODEL

# Default polling interval for vision requests (seconds).
# fal_client.subscribe() defaults to ~200ms which floods the API.
_VISION_POLL_INTERVAL = 1.0


def _sanitize_for_log(arguments: dict) -> dict:
    """Return a copy of arguments with base64 data URIs replaced by size placeholders."""
    sanitized = {}
    for k, v in arguments.items():
        if k == "image_urls" and isinstance(v, list):
            sanitized[k] = [
                f"<data_uri:{len(url)}chars>" if url.startswith("data:") else url
                for url in v
            ]
        elif isinstance(v, str) and v.startswith("data:") and len(v) > 200:
            sanitized[k] = f"<data_uri:{len(v)}chars>"
        else:
            sanitized[k] = v
    return sanitized


def build_router_request(
    model: str,
    prompt: str,
    max_tokens: int,
    image_urls: list[str] | None = None,
    temperature: float | None = None,
    system_prompt: str | None = None,
) -> tuple[str, dict]:
    """Build (endpoint, arguments) for a fal OpenRouter call — the one place router args are made.

    Uses the vision router when images are attached and the text router otherwise.
    ``temperature`` is omitted unless the catalog says the model accepts it.
    """
    arguments: dict = {"prompt": prompt, "model": model, "max_tokens": max_tokens}
    if system_prompt:
        arguments["system_prompt"] = system_prompt
    if image_urls:
        arguments["image_urls"] = image_urls
    lm = get_language_model(model)
    if lm is not None and lm.requires_reasoning:
        arguments["reasoning"] = True
        arguments["max_tokens"] = max(max_tokens, 4096)
    if temperature is not None and lm is not None and lm.supports_temperature:
        arguments["temperature"] = temperature
    return (FAL_VISION_ENDPOINT if image_urls else FAL_ROUTER_ENDPOINT), arguments


def _fal_submit_and_poll(endpoint: str, arguments: dict, poll_interval: float = _VISION_POLL_INTERVAL) -> dict:
    """Submit a fal.ai request and poll for completion at a sane interval."""
    from fal_client.client import Completed

    logger.info("FAL REQUEST | endpoint=%s args=%s", endpoint, _sanitize_for_log(arguments))
    handle = fal_client.submit(endpoint, arguments=arguments)
    while True:
        status = handle.status(with_logs=False)
        if isinstance(status, Completed):
            break
        time.sleep(poll_interval)
    result = handle.get()
    logger.info("FAL RESPONSE | endpoint=%s request_id=%s result=%s", endpoint, handle.request_id, result)
    return result


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

        endpoint, args = build_router_request(
            self.model, tag_prompt, self.token_limit,
            image_urls=[data_uri], temperature=self.temperature,
        )

        start = time.monotonic()
        try:
            with provider_span("fal_vision", "tag", self.model) as span:
                result = _fal_submit_and_poll(endpoint, arguments=args)
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

        endpoint, args = build_router_request(
            self.model, description_prompt, self.token_limit,
            image_urls=[data_uri], temperature=self.temperature,
        )

        start = time.monotonic()
        try:
            with provider_span("fal_vision", "describe", self.model) as span:
                result = _fal_submit_and_poll(endpoint, arguments=args)
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

        # Use parsed JSON "description" if available, otherwise fall back to
        # the raw text response (custom prompts return plain text, not JSON).
        description = parsed.get("description") or content or ""

        return DescriptionResult(
            description=description,
            model=self.model,
            raw_response={"content": content},
        )

    def get_model_name(self) -> str:
        return self.model


class FalVisionEvaluator(BaseEvaluator):
    """fal.ai OpenRouter vision-based image pair evaluator."""

    def __init__(self, api_key: str | None = None, model: str | None = None, temperature: float | None = None):
        _ensure_fal_key(api_key)
        self.model = model or DEFAULT_FAL_VISION_MODEL
        self.temperature = temperature

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
                endpoint, args = build_router_request(
                    self.model, prompt, 1000,
                    image_urls=[orig_uri, gen_uri], temperature=self.temperature,
                )
                result = _fal_submit_and_poll(endpoint, arguments=args)
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
                endpoint, args = build_router_request(
                    self.model, prompt, 1000,
                    image_urls=[data_uri], temperature=self.temperature,
                )
                result = _fal_submit_and_poll(endpoint, arguments=args)
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
                endpoint, args = build_router_request(
                    self.model, prompt, 1000, temperature=self.temperature,
                )
                result = _fal_submit_and_poll(endpoint, arguments=args)
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
                endpoint, args = build_router_request(
                    self.model, prompt, 2000, temperature=self.temperature,
                )
                result = _fal_submit_and_poll(endpoint, arguments=args)
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


class FalClusterSummarizer(BaseClusterSummarizer):
    """fal.ai OpenRouter text-only cluster summarizer."""

    def __init__(self, api_key: str | None = None, model: str | None = None, max_tokens: dict | None = None):
        _ensure_fal_key(api_key)
        self.model = model or DEFAULT_FAL_VISION_MODEL
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
            with provider_span("fal_vision", "summarize_cluster", self.model) as span:
                endpoint, args = build_router_request(self.model, prompt, self.token_limit)
                result = _fal_submit_and_poll(endpoint, arguments=args)
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
                message=f"fal.ai OpenRouter summarize completed ({self.model})",
                provider="fal", model=self.model, operation="summarize",
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
                message=f"fal.ai OpenRouter summarize failed: {e}",
                level=LogLevel.ERROR, provider="fal", model=self.model,
                operation="summarize", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e)},
            )
            raise

        parsed = _extract_json(content)
        return ClusterSummaryResult(
            summary_title=parsed.get("summary_title", "Untitled Cluster"),
            summary_description=parsed.get("summary_description", ""),
            model=self.model,
        )

    def get_model_name(self) -> str:
        return self.model


@dataclass
class TextCompletion:
    """Result of a text-only fal OpenRouter call."""

    text: str
    input_tokens: int | None
    output_tokens: int | None
    provider_cost: float | None
    usage: dict


async def fal_text_completion(
    prompt: str,
    model: str,
    max_tokens: int,
    api_key: str | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    image_urls: list[str] | None = None,
) -> TextCompletion:
    """Run a router call without blocking the event loop (for API routes).

    Text-only unless *image_urls* is given, in which case the vision router is used.
    """
    _ensure_fal_key(api_key)
    endpoint, args = build_router_request(
        model, prompt, max_tokens, image_urls=image_urls, temperature=temperature, system_prompt=system_prompt,
    )
    result = await asyncio.to_thread(_fal_submit_and_poll, endpoint, args)
    usage = result.get("usage") or {}
    return TextCompletion(
        text=(result.get("output") or "").strip(),
        input_tokens=usage.get("prompt_tokens") or usage.get("input_tokens"),
        output_tokens=usage.get("completion_tokens") or usage.get("output_tokens"),
        provider_cost=usage.get("cost"),
        usage=usage,
    )
