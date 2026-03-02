"""Provider-level tracing via OpenTelemetry spans.

Wraps AI provider calls (OpenAI, Anthropic, fal.ai) with OTel spans so they
appear in Sentry Performance traces.
"""
from contextlib import contextmanager


@contextmanager
def provider_span(provider: str, operation: str, model: str = ""):
    """Create an OTel span for an AI provider call.

    Usage:
        with provider_span("openai", "tag", "gpt-4o") as span:
            result = await client.chat(...)
            if span:
                span.set_attribute("ai.tokens.input", result.input_tokens)
    """
    try:
        from opentelemetry import trace
        tracer = trace.get_tracer("cura.providers")
        with tracer.start_as_current_span(
            f"{provider}.{operation}",
            attributes={
                "ai.provider": provider,
                "ai.operation": operation,
                "ai.model": model,
            },
        ) as span:
            yield span
    except ImportError:
        yield None
    except Exception:
        yield None
