"""Provider factory for AI services."""
import logging
from typing import Literal

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.providers.base import (
    BaseClusterSummarizer,
    BaseDescriber,
    BaseEditor,
    BaseEmbedder,
    BaseEvaluator,
    BaseGenerator,
    BaseTagger,
    BaseTrainer,
    ClusterSummaryResult,
    DescriptionResult,
    EditResult,
    EmbeddingResult,
    GenerationResult,
    TaggingResult,
    TrainingResult,
    VisionEvalResult,
)
from app.providers.fal_provider import FalEditor, FalGenerator, FalTrainer
from app.providers.fal_vision_provider import (
    FalClusterSummarizer,
    FalVisionDescriber,
    FalVisionEvaluator,
    FalVisionTagger,
)
from app.providers.openai_provider import OpenAIEmbedder
from app.services.model_catalog import DEFAULT_EDIT_MODEL, DEFAULT_GENERATION_MODEL

logger = logging.getLogger(__name__)
settings = get_settings()


def _resolve_config(db: Session | None, user_id: int | None = None):
    """Resolve API keys from platform env vars and provider config from DB.

    Returns (key_map, provider_config) where key_map is {provider_name: key_value}
    and provider_config is the merged config dict.
    """
    # Platform-owned API keys from env vars
    keys = {
        "openai": settings.openai_api_key or None,
        "fal": settings.fal_api_key or None,
    }

    if db is None:
        return keys, {}

    try:
        from app.services.settings_service import get_settings_service

        # Pre-flight balance check
        if user_id:
            from app.services.billing_service import BillingService
            BillingService(db, user_id).check_balance_or_raise()

        # Override env var keys with active DB-stored platform keys
        try:
            from app.models.api_key import APIKey
            from app.services.encryption import decrypt_api_key

            platform_keys = db.query(APIKey).filter(APIKey.status == "active").all()
            for pk in platform_keys:
                try:
                    decrypted = decrypt_api_key(pk.encrypted_key)
                    if decrypted:
                        keys[pk.provider] = decrypted
                except Exception:
                    pass
        except Exception:
            pass

        settings_service = get_settings_service(db, user_id) if user_id else None
        provider_config = settings_service.get_provider_config() if settings_service else {}

        return keys, provider_config
    except Exception as e:
        # Re-raise InsufficientBalanceError so callers can handle it
        from app.services.billing_service import InsufficientBalanceError
        if isinstance(e, InsufficientBalanceError):
            raise
        logger.warning(f"Failed to resolve config from DB: {e}")
        return keys, {}


def _token_config(config: dict) -> dict:
    """Build token limits dict from provider config."""
    return {
        "tag": config.get("max_tokens_tagging", 1000),
        "describe": config.get("max_tokens_description", 3000),
        "summarize": config.get("max_tokens_summarization", 500),
    }


def _temperature_config(config: dict) -> float:
    """Read vision_temperature from provider config."""
    return float(config.get("vision_temperature", 1.0))


def get_tagger(
    db: Session | None = None,
    user_id: int | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens_override: int | None = None,
) -> BaseTagger:
    """Get the fal OpenRouter vision tagger."""
    keys, config = _resolve_config(db, user_id)
    tok = _token_config(config)
    if max_tokens_override is not None:
        tok["tag"] = max_tokens_override
    temp = temperature if temperature is not None else _temperature_config(config)
    return FalVisionTagger(
        api_key=keys.get("fal"),
        model=model or config.get("fal_vision_model"),
        max_tokens=tok,
        temperature=temp,
    )


def get_describer(
    db: Session | None = None,
    user_id: int | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens_override: int | None = None,
) -> BaseDescriber:
    """Get the fal OpenRouter vision describer."""
    keys, config = _resolve_config(db, user_id)
    tok = _token_config(config)
    if max_tokens_override is not None:
        tok["describe"] = max_tokens_override
    temp = temperature if temperature is not None else _temperature_config(config)
    return FalVisionDescriber(
        api_key=keys.get("fal"),
        model=model or config.get("fal_vision_model"),
        max_tokens=tok,
        temperature=temp,
    )


def get_embedder(
    provider: Literal["openai", "local"] | None = None,
    db: Session | None = None,
    user_id: int | None = None,
) -> BaseEmbedder:
    """Get embedder instance for the specified provider."""
    keys, config = _resolve_config(db, user_id)
    provider = provider or config.get("embedding_provider") or settings.default_embedding_provider
    if provider == "openai":
        return OpenAIEmbedder(
            api_key=keys.get("openai"),
            model=config.get("openai_embedding_model"),
        )
    else:
        raise ValueError(f"Unknown embedder provider: {provider}")


def get_cluster_summarizer(
    db: Session | None = None,
    user_id: int | None = None,
) -> BaseClusterSummarizer:
    """Get the fal OpenRouter cluster summarizer (text-only, uses the language model setting)."""
    keys, config = _resolve_config(db, user_id)
    return FalClusterSummarizer(
        api_key=keys.get("fal"),
        model=config.get("fal_language_model"),
        max_tokens=_token_config(config),
    )


def get_trainer(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    base_model: str = "flux-2",
    user_id: int | None = None,
) -> BaseTrainer:
    """Get trainer instance for the specified provider."""
    keys, _ = _resolve_config(db, user_id)
    provider = provider or settings.default_training_provider
    if provider == "fal":
        return FalTrainer(api_key=keys.get("fal"), base_model=base_model)
    else:
        raise ValueError(f"Unknown trainer provider: {provider}")


def get_generator(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    base_model: str = DEFAULT_GENERATION_MODEL,
    user_id: int | None = None,
) -> BaseGenerator:
    """Get generator instance for the specified provider."""
    keys, _ = _resolve_config(db, user_id)
    provider = provider or settings.default_generation_provider
    if provider == "fal":
        return FalGenerator(api_key=keys.get("fal"), base_model=base_model)
    else:
        raise ValueError(f"Unknown generator provider: {provider}")


def get_editor(
    provider: Literal["fal"] | None = None,
    db: Session | None = None,
    edit_model: str = DEFAULT_EDIT_MODEL,
    user_id: int | None = None,
) -> BaseEditor:
    """Get editor instance for the specified provider."""
    keys, _ = _resolve_config(db, user_id)
    provider = provider or "fal"
    if provider == "fal":
        return FalEditor(api_key=keys.get("fal"), edit_model=edit_model)
    else:
        raise ValueError(f"Unknown editor provider: {provider}")


def get_evaluator(
    db: Session | None = None,
    user_id: int | None = None,
) -> BaseEvaluator:
    """Get the fal OpenRouter vision evaluator."""
    keys, config = _resolve_config(db, user_id)
    return FalVisionEvaluator(
        api_key=keys.get("fal"),
        model=config.get("fal_vision_model"),
        temperature=_temperature_config(config),
    )


__all__ = [
    "BaseTagger",
    "BaseDescriber",
    "BaseEditor",
    "BaseEmbedder",
    "BaseEvaluator",
    "BaseClusterSummarizer",
    "BaseTrainer",
    "BaseGenerator",
    "TaggingResult",
    "DescriptionResult",
    "EditResult",
    "EmbeddingResult",
    "ClusterSummaryResult",
    "TrainingResult",
    "GenerationResult",
    "VisionEvalResult",
    "get_tagger",
    "get_describer",
    "get_editor",
    "get_embedder",
    "get_cluster_summarizer",
    "get_trainer",
    "get_generator",
    "get_evaluator",
]
