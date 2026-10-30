"""OpenAI provider implementation for text embeddings."""
import logging
import time

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.models.pipeline_log import LogCategory, LogLevel
from app.providers.base import BaseEmbedder, EmbeddingResult
from app.providers.tracing import provider_span
from app.services.log_service import write_log

logger = logging.getLogger(__name__)
settings = get_settings()


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
                extra={
                    "request_prompt": text[:2000],
                },
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            write_log(
                category=LogCategory.API_CALL,
                message=f"OpenAI embed failed: {e}",
                level=LogLevel.ERROR, provider="openai", model=self.model,
                operation="embed", duration_ms=round(elapsed, 1), success=False,
                extra={"error": str(e), "request_prompt": text[:2000]},
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
