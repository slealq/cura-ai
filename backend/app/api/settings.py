"""Settings API endpoints."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import get_current_user, require_admin
from app.db.base import get_db
from app.models.api_key import APIProvider
from app.models.user import User
from app.services.settings_service import (
    DEFAULT_CLUSTERING_CONFIG,
    DEFAULT_DESCRIPTION_PROMPT,
    DEFAULT_EDIT_CONFIGS,
    DEFAULT_GENERATION_CONFIG,
    DEFAULT_GENERATION_CONFIGS,
    DEFAULT_PROVIDER_CONFIG,
    DEFAULT_TAG_PROMPT,
    DEFAULT_TRAINING_CONFIG,
    DEFAULT_TRAINING_CONFIGS,
    get_settings_service,
)

logger = logging.getLogger(__name__)
app_settings = get_settings()
router = APIRouter(prefix="/settings", tags=["settings"])


# --- Schemas ---


class PromptSettingsRequest(BaseModel):
    """Request to update prompt settings."""

    description_prompt: str | None = None
    tag_prompt: str | None = None


class PromptSettingsResponse(BaseModel):
    """Response with current prompt settings."""

    description_prompt: str
    tag_prompt: str
    description_prompt_custom: bool
    tag_prompt_custom: bool


class PromptSuggestRequest(BaseModel):
    """Request to get AI-suggested prompt edits."""

    current_prompt: str
    change_request: str
    prompt_type: Literal["description", "tag"]


class PromptSuggestResponse(BaseModel):
    """Response with suggested prompt text."""

    suggested_prompt: str


class PresetResponse(BaseModel):
    """Response for a single preset."""

    id: int
    name: str
    tag_prompt: str
    description_prompt: str
    is_default: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


class PresetCreateRequest(BaseModel):
    """Request to create a preset."""

    name: str
    tag_prompt: str
    description_prompt: str


class PresetUpdateRequest(BaseModel):
    """Request to update a preset."""

    name: str | None = None
    tag_prompt: str | None = None
    description_prompt: str | None = None


class APIKeyResponse(BaseModel):
    """Response for a stored API key (never exposes the actual key)."""

    provider: str
    key_suffix: str | None
    status: str
    last_validated_at: str | None
    last_error: str | None


class APIKeySaveRequest(BaseModel):
    """Request to save/update an API key."""

    key: str


class ProviderConfigResponse(BaseModel):
    """Current provider configuration."""

    vision_provider: str
    embedding_provider: str
    openai_vision_model: str
    openai_embedding_model: str
    anthropic_vision_model: str
    fal_vision_model: str
    max_tokens_tagging: int
    max_tokens_description: int
    max_tokens_summarization: int
    language_provider: str
    openai_language_model: str
    anthropic_language_model: str
    fal_language_model: str
    max_tokens_expansion: int
    max_tokens_suggestion: int


class ProviderConfigUpdateRequest(BaseModel):
    """Partial update for provider configuration."""

    vision_provider: str | None = None
    embedding_provider: str | None = None
    openai_vision_model: str | None = None
    openai_embedding_model: str | None = None
    anthropic_vision_model: str | None = None
    fal_vision_model: str | None = None
    max_tokens_tagging: int | None = None
    max_tokens_description: int | None = None
    max_tokens_summarization: int | None = None
    language_provider: str | None = None
    openai_language_model: str | None = None
    anthropic_language_model: str | None = None
    fal_language_model: str | None = None
    max_tokens_expansion: int | None = None
    max_tokens_suggestion: int | None = None


class ProviderModelInfo(BaseModel):
    """Info about a model available from a provider."""

    id: str
    name: str
    capabilities: list[str]


class ClusteringConfigResponse(BaseModel):
    """Current clustering configuration."""

    method: str
    use_umap: bool
    umap_n_components: int
    umap_n_neighbors: int
    umap_min_dist: float
    umap_metric: str
    hdbscan_min_cluster_size: int
    hdbscan_min_samples: int
    hdbscan_cluster_selection_method: str
    kmeans_max_clusters: int


class ClusteringConfigUpdateRequest(BaseModel):
    """Partial update for clustering configuration."""

    method: str | None = None
    use_umap: bool | None = None
    umap_n_components: int | None = None
    umap_n_neighbors: int | None = None
    umap_min_dist: float | None = None
    umap_metric: str | None = None
    hdbscan_min_cluster_size: int | None = None
    hdbscan_min_samples: int | None = None
    hdbscan_cluster_selection_method: str | None = None
    kmeans_max_clusters: int | None = None


def _preset_to_response(preset) -> PresetResponse:
    return PresetResponse(
        id=preset.id,
        name=preset.name,
        tag_prompt=preset.tag_prompt,
        description_prompt=preset.description_prompt,
        is_default=preset.is_default,
        created_at=preset.created_at.isoformat(),
        updated_at=preset.updated_at.isoformat(),
    )


# --- Preset endpoints ---


@router.get("/presets", response_model=list[PresetResponse])
async def list_presets(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """List all prompt presets."""
    service = get_settings_service(db, current_user.id)
    return [_preset_to_response(p) for p in service.list_presets()]


@router.post("/presets", response_model=PresetResponse, status_code=201)
async def create_preset(request: PresetCreateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Create a new prompt preset."""
    service = get_settings_service(db, current_user.id)
    try:
        preset = service.create_preset(request.name, request.tag_prompt, request.description_prompt)
    except Exception:
        raise HTTPException(status_code=400, detail="A preset with that name already exists")
    return _preset_to_response(preset)


@router.get("/presets/{preset_id}", response_model=PresetResponse)
async def get_preset(preset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get a single preset by ID."""
    service = get_settings_service(db, current_user.id)
    preset = service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _preset_to_response(preset)


@router.put("/presets/{preset_id}", response_model=PresetResponse)
async def update_preset(preset_id: int, request: PresetUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Update a preset's name and/or prompts."""
    service = get_settings_service(db, current_user.id)
    preset = service.update_preset(preset_id, name=request.name, tag_prompt=request.tag_prompt, description_prompt=request.description_prompt)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _preset_to_response(preset)


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Delete a preset (cannot delete the active preset)."""
    service = get_settings_service(db, current_user.id)
    preset = service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if not service.delete_preset(preset_id):
        raise HTTPException(status_code=403, detail="Cannot delete the active preset")


@router.post("/presets/{preset_id}/activate", response_model=PresetResponse)
async def activate_preset(preset_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Set a preset as the active default."""
    service = get_settings_service(db, current_user.id)
    preset = service.set_default_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _preset_to_response(preset)


# --- Legacy prompt endpoints (backward compat, operate on active preset) ---


@router.get("/prompts", response_model=PromptSettingsResponse)
async def get_prompt_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get current default prompt settings."""
    settings_service = get_settings_service(db, current_user.id)
    active = settings_service._ensure_default_preset()
    return PromptSettingsResponse(
        description_prompt=active.description_prompt,
        tag_prompt=active.tag_prompt,
        description_prompt_custom=active.description_prompt != DEFAULT_DESCRIPTION_PROMPT,
        tag_prompt_custom=active.tag_prompt != DEFAULT_TAG_PROMPT,
    )


@router.put("/prompts", response_model=PromptSettingsResponse)
async def update_prompt_settings(
    request: PromptSettingsRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Update active preset's prompts."""
    settings_service = get_settings_service(db, current_user.id)
    active = settings_service._ensure_default_preset()

    settings_service.update_preset(
        active.id,
        tag_prompt=request.tag_prompt,
        description_prompt=request.description_prompt,
    )

    active = settings_service._ensure_default_preset()
    return PromptSettingsResponse(
        description_prompt=active.description_prompt,
        tag_prompt=active.tag_prompt,
        description_prompt_custom=active.description_prompt != DEFAULT_DESCRIPTION_PROMPT,
        tag_prompt_custom=active.tag_prompt != DEFAULT_TAG_PROMPT,
    )


@router.post("/prompts/reset", response_model=PromptSettingsResponse)
async def reset_prompt_settings(
    prompt_type: Literal["description", "tag", "all"] = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reset active preset's prompts to factory defaults."""
    settings_service = get_settings_service(db, current_user.id)
    active = settings_service._ensure_default_preset()

    tag = None
    desc = None
    if prompt_type in ("tag", "all"):
        tag = DEFAULT_TAG_PROMPT
    if prompt_type in ("description", "all"):
        desc = DEFAULT_DESCRIPTION_PROMPT

    settings_service.update_preset(active.id, tag_prompt=tag, description_prompt=desc)

    active = settings_service._ensure_default_preset()
    return PromptSettingsResponse(
        description_prompt=active.description_prompt,
        tag_prompt=active.tag_prompt,
        description_prompt_custom=active.description_prompt != DEFAULT_DESCRIPTION_PROMPT,
        tag_prompt_custom=active.tag_prompt != DEFAULT_TAG_PROMPT,
    )


@router.post("/prompts/suggest", response_model=PromptSuggestResponse)
async def suggest_prompt(request: PromptSuggestRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Use AI to suggest edits to a prompt based on a change request."""
    try:
        from app.core.config import get_settings
        from app.services.billing_service import BillingService, InsufficientBalanceError

        try:
            BillingService(db, current_user.id).check_balance_or_raise()
        except InsufficientBalanceError:
            raise HTTPException(status_code=402, detail="Insufficient credits")

        app_settings = get_settings()
        openai_key = app_settings.openai_api_key
        if not openai_key:
            raise HTTPException(status_code=400, detail="OpenAI API key not configured on the platform.")
        client = AsyncOpenAI(api_key=openai_key)

        # Use language model settings from provider config
        settings_service = get_settings_service(db, current_user.id)
        provider_config = settings_service.get_provider_config()
        suggestion_model = provider_config.get("openai_language_model", "gpt-4o-mini")
        suggestion_max_tokens = provider_config.get("max_tokens_suggestion", 2000)

        system_prompt = (
            f"You are helping edit an AI prompt for image {request.prompt_type} generation. "
            "The user will provide the current prompt and a requested change. "
            "Return ONLY the new complete prompt incorporating the requested changes. "
            "Do not include any explanation or commentary, just the updated prompt text."
        )

        response = await client.chat.completions.create(
            model=suggestion_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Current prompt:\n{request.current_prompt}\n\n"
                        f"Requested change:\n{request.change_request}"
                    ),
                },
            ],
            max_tokens=suggestion_max_tokens,
        )

        suggested = response.choices[0].message.content or ""
        return PromptSuggestResponse(suggested_prompt=suggested.strip())

    except Exception as e:
        logger.error(f"Failed to suggest prompt: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate suggestion: {str(e)}")


# --- API Key endpoints ---


def _api_key_to_response(key) -> APIKeyResponse:
    return APIKeyResponse(
        provider=key.provider,
        key_suffix=key.key_suffix,
        status=key.status,
        last_validated_at=key.last_validated_at.isoformat() if key.last_validated_at else None,
        last_error=key.last_error,
    )


ENV_VAR_MAP = {
    APIProvider.OPENAI: app_settings.openai_api_key,
    APIProvider.ANTHROPIC: app_settings.anthropic_api_key,
    APIProvider.FAL: app_settings.fal_api_key,
    # Sentry has no env var fallback — always stored in DB
}


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """List platform API key status for all providers (admin only)."""
    from app.services.api_key_service import get_api_key_service

    service = get_api_key_service(db, current_user.id)
    results = []
    for provider in APIProvider:
        key = service.get_key(provider)
        if key:
            results.append(_api_key_to_response(key))
        else:
            env_val = ENV_VAR_MAP.get(provider) or None
            if env_val:
                results.append(APIKeyResponse(
                    provider=provider.value,
                    key_suffix=env_val[-4:] if len(env_val) >= 4 else env_val,
                    status="env_var",
                    last_validated_at=None,
                    last_error="Configured via environment variable",
                ))
            else:
                results.append(APIKeyResponse(
                    provider=provider.value,
                    key_suffix=None,
                    status="not_configured",
                    last_validated_at=None,
                    last_error=None,
                ))
    return results


@router.put("/api-keys/{provider}", response_model=APIKeyResponse)
async def save_api_key(
    provider: str,
    request: APIKeySaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Save and validate a platform API key (admin only)."""
    from app.services.api_key_service import get_api_key_service

    try:
        api_provider = APIProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    service = get_api_key_service(db, current_user.id)
    key, _result = await service.validate_and_save_key(api_provider, request.key)
    return _api_key_to_response(key)


@router.post("/api-keys/{provider}/validate", response_model=APIKeyResponse)
async def validate_api_key(
    provider: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Re-validate an existing platform API key (admin only)."""
    from app.services.api_key_service import get_api_key_service

    try:
        api_provider = APIProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    service = get_api_key_service(db, current_user.id)
    existing = service.get_key(api_provider)
    if not existing:
        raise HTTPException(status_code=404, detail=f"No stored key for {provider}")

    decrypted = service.get_decrypted_key(api_provider)
    if not decrypted:
        raise HTTPException(status_code=500, detail="Failed to decrypt stored key")

    key, _result = await service.validate_and_save_key(api_provider, decrypted)
    return _api_key_to_response(key)


@router.delete("/api-keys/{provider}", status_code=204)
async def delete_api_key(
    provider: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Delete a platform API key (admin only)."""
    from app.services.api_key_service import get_api_key_service

    try:
        api_provider = APIProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    service = get_api_key_service(db, current_user.id)
    if not service.delete_key(api_provider):
        raise HTTPException(status_code=404, detail=f"No stored key for {provider}")


@router.get("/sentry-dsn")
async def get_sentry_dsn(db: Session = Depends(get_db)):
    """Get the Sentry DSN for client-side initialization (public, no auth required).

    Sentry DSNs are write-only ingestion URLs and safe to expose to clients.
    """
    from app.models.api_key import APIKey

    key = db.query(APIKey).filter(APIKey.provider == "sentry", APIKey.status == "active").first()
    if key:
        from app.services.encryption import decrypt_api_key
        return {"dsn": decrypt_api_key(key.encrypted_key)}
    return {"dsn": None}


# --- Provider config endpoints ---


@router.get("/providers", response_model=ProviderConfigResponse)
async def get_provider_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get current provider configuration."""
    service = get_settings_service(db, current_user.id)
    return service.get_provider_config()


@router.put("/providers", response_model=ProviderConfigResponse)
async def update_provider_config(
    request: ProviderConfigUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Update provider configuration (partial update, merges with defaults)."""
    service = get_settings_service(db, current_user.id)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    return service.set_provider_config(update)


@router.post("/providers/reset", response_model=ProviderConfigResponse)
async def reset_provider_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reset provider configuration to defaults."""
    service = get_settings_service(db, current_user.id)
    service.delete_setting("provider_config")
    return DEFAULT_PROVIDER_CONFIG


# --- Model discovery endpoint ---


@router.get("/models/{provider}", response_model=list[ProviderModelInfo])
async def get_provider_models(provider: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get available models for a provider."""
    if provider == "openai":
        return await _get_openai_models(db, current_user.id)
    elif provider == "anthropic":
        return _get_anthropic_models()
    elif provider == "fal":
        return _get_fal_models()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")


CURATED_OPENAI_VISION_MODELS = [
    ProviderModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", capabilities=["vision", "chat"]),
    ProviderModelInfo(id="gpt-4o", name="GPT-4o", capabilities=["vision", "chat"]),
    ProviderModelInfo(id="gpt-5-mini", name="GPT-5 Mini", capabilities=["vision", "chat"]),
    ProviderModelInfo(id="gpt-5.2", name="GPT-5.2", capabilities=["vision", "chat"]),
]

FALLBACK_EMBEDDING_MODELS = [
    ProviderModelInfo(id="text-embedding-3-small", name="Text Embedding 3 Small", capabilities=["embedding"]),
    ProviderModelInfo(id="text-embedding-3-large", name="Text Embedding 3 Large", capabilities=["embedding"]),
]


async def _get_openai_models(db: Session, user_id: int) -> list[ProviderModelInfo]:
    """Return curated vision models + dynamically discovered embedding models."""
    from app.services.api_key_service import get_api_key_service as get_aks

    key_service = get_aks(db, user_id)
    api_key = key_service.resolve_key(APIProvider.OPENAI)
    if not api_key:
        api_key = app_settings.openai_api_key or None
    if not api_key:
        return CURATED_OPENAI_VISION_MODELS + FALLBACK_EMBEDDING_MODELS

    # Dynamically discover embedding models
    embedding_models: list[ProviderModelInfo] = []
    try:
        client = AsyncOpenAI(api_key=api_key)
        models_resp = await client.models.list()
        for m in models_resp.data:
            if m.id.startswith("text-embedding-"):
                embedding_models.append(ProviderModelInfo(
                    id=m.id,
                    name=m.id.replace("-", " ").title(),
                    capabilities=["embedding"],
                ))
        embedding_models.sort(key=lambda x: x.id)
    except Exception as e:
        logger.warning(f"Failed to fetch OpenAI embedding models: {e}")
        embedding_models = list(FALLBACK_EMBEDDING_MODELS)

    if not embedding_models:
        embedding_models = list(FALLBACK_EMBEDDING_MODELS)

    return CURATED_OPENAI_VISION_MODELS + embedding_models


def _get_anthropic_models() -> list[ProviderModelInfo]:
    """Return curated list of Anthropic Claude models with vision support."""
    return [
        ProviderModelInfo(id="claude-3-haiku-20240307", name="Claude Haiku 3", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="claude-haiku-4-5-20251001", name="Claude Haiku 4.5", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="claude-sonnet-4-6", name="Claude Sonnet 4.6", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="claude-opus-4-6", name="Claude Opus 4.6", capabilities=["vision", "chat"]),
    ]


def _get_fal_models() -> list[ProviderModelInfo]:
    """Return supported fal.ai endpoints and OpenRouter vision models."""
    return [
        # OpenRouter vision models
        ProviderModelInfo(id="x-ai/grok-4-fast", name="Grok 4 Fast", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="qwen/qwen3-vl-235b-a22b-instruct", name="Qwen3 VL 235B", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="google/gemini-2.5-flash", name="Gemini 2.5 Flash", capabilities=["vision", "chat"]),
        # Generation/training endpoints
        ProviderModelInfo(id="fal-ai/flux/dev", name="Flux.1 Dev", capabilities=["generation"]),
        ProviderModelInfo(id="fal-ai/flux-lora", name="Flux LoRA", capabilities=["generation", "lora"]),
        ProviderModelInfo(id="fal-ai/flux-lora-fast-training", name="Flux LoRA Fast Training", capabilities=["training"]),
        # Generation endpoints (no LoRA)
        ProviderModelInfo(id="fal-ai/nano-banana-pro", name="Nano Banana Pro", capabilities=["generation"]),
        # Edit endpoints
        ProviderModelInfo(id="qwen-image-max-edit", name="Qwen Image Max Edit", capabilities=["edit"]),
        ProviderModelInfo(id="nano-banana-pro-edit", name="Nano Banana Pro Edit", capabilities=["edit"]),
    ]


# --- Clustering config endpoints ---


@router.get("/clustering", response_model=ClusteringConfigResponse)
async def get_clustering_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get current clustering configuration."""
    service = get_settings_service(db, current_user.id)
    return service.get_clustering_config()


@router.put("/clustering", response_model=ClusteringConfigResponse)
async def update_clustering_config(
    request: ClusteringConfigUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Update clustering configuration (partial update, merges with defaults)."""
    service = get_settings_service(db, current_user.id)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    config = service.set_clustering_config(update)
    return config


@router.post("/clustering/reset", response_model=ClusteringConfigResponse)
async def reset_clustering_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reset clustering configuration to defaults."""
    service = get_settings_service(db, current_user.id)
    service.delete_setting("clustering_config")
    return DEFAULT_CLUSTERING_CONFIG


# --- Generation config endpoints ---


class BaseModelRequest(BaseModel):
    """Request to set the active base model."""

    base_model: str


class BaseModelResponse(BaseModel):
    """Response with the active base model."""

    base_model: str


class GenerationConfigResponse(BaseModel):
    """Current generation configuration."""

    width: int
    height: int
    num_inference_steps: int
    guidance_scale: float
    default_lora_scale: float


class GenerationConfigUpdateRequest(BaseModel):
    """Partial update for generation configuration."""

    width: int | None = None
    height: int | None = None
    num_inference_steps: int | None = None
    guidance_scale: float | None = None
    default_lora_scale: float | None = None


@router.get("/base-model", response_model=BaseModelResponse)
async def get_base_model(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get the active base model."""
    service = get_settings_service(db, current_user.id)
    return {"base_model": service.get_base_model()}


@router.put("/base-model", response_model=BaseModelResponse)
async def update_base_model(request: BaseModelRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Set the active base model."""
    service = get_settings_service(db, current_user.id)
    return {"base_model": service.set_base_model(request.base_model)}


class EditModelRequest(BaseModel):
    """Request to set the default edit model."""

    edit_model: str


class EditModelResponse(BaseModel):
    """Response with the default edit model."""

    edit_model: str


@router.get("/edit-model", response_model=EditModelResponse)
async def get_edit_model(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get the default edit model."""
    service = get_settings_service(db, current_user.id)
    return {"edit_model": service.get_edit_model()}


@router.put("/edit-model", response_model=EditModelResponse)
async def update_edit_model(request: EditModelRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Set the default edit model."""
    service = get_settings_service(db, current_user.id)
    return {"edit_model": service.set_edit_model(request.edit_model)}


@router.get("/generation", response_model=GenerationConfigResponse)
async def get_generation_config(base_model: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get current generation configuration, optionally scoped to a base model."""
    service = get_settings_service(db, current_user.id)
    return service.get_generation_config(base_model)


@router.put("/generation", response_model=GenerationConfigResponse)
async def update_generation_config(
    request: GenerationConfigUpdateRequest, base_model: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Update generation configuration, optionally scoped to a base model."""
    service = get_settings_service(db, current_user.id)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    return service.set_generation_config(update, base_model)


@router.post("/generation/reset", response_model=GenerationConfigResponse)
async def reset_generation_config(base_model: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reset generation configuration to defaults."""
    service = get_settings_service(db, current_user.id)
    if base_model:
        service.delete_setting(f"generation_config:{base_model}")
        return DEFAULT_GENERATION_CONFIGS.get(base_model, DEFAULT_GENERATION_CONFIG)
    service.delete_setting("generation_config")
    return DEFAULT_GENERATION_CONFIG


# --- Training config endpoints ---


class TrainingConfigResponse(BaseModel):
    """Current training configuration."""

    steps: int | None = None
    is_style: bool | None = None
    learning_rate: float | None = None


class TrainingConfigUpdateRequest(BaseModel):
    """Partial update for training configuration."""

    steps: int | None = None
    is_style: bool | None = None
    learning_rate: float | None = None


@router.get("/training", response_model=TrainingConfigResponse)
async def get_training_config(base_model: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get current training configuration, optionally scoped to a base model."""
    service = get_settings_service(db, current_user.id)
    return service.get_training_config(base_model)


@router.put("/training", response_model=TrainingConfigResponse)
async def update_training_config(
    request: TrainingConfigUpdateRequest, base_model: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Update training configuration, optionally scoped to a base model."""
    service = get_settings_service(db, current_user.id)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    return service.set_training_config(update, base_model)


@router.post("/training/reset", response_model=TrainingConfigResponse)
async def reset_training_config(base_model: str | None = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reset training configuration to defaults."""
    service = get_settings_service(db, current_user.id)
    if base_model:
        service.delete_setting(f"training_config:{base_model}")
        return DEFAULT_TRAINING_CONFIGS.get(base_model, DEFAULT_TRAINING_CONFIG)
    service.delete_setting("training_config")
    return DEFAULT_TRAINING_CONFIG


# --- Edit config endpoints ---


class EditConfigResponse(BaseModel):
    """Current edit configuration."""

    image_size: str | dict = "square_hd"
    num_images: int = 1
    output_format: str = "png"
    enable_prompt_expansion: bool = True
    enable_safety_checker: bool = True


class EditConfigUpdateRequest(BaseModel):
    """Partial update for edit configuration."""

    image_size: str | dict | None = None
    num_images: int | None = None
    output_format: str | None = None
    enable_prompt_expansion: bool | None = None
    enable_safety_checker: bool | None = None


@router.get("/edit", response_model=EditConfigResponse)
async def get_edit_config(edit_model: str = "qwen-image-max-edit", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Get current edit configuration for a specific edit model."""
    service = get_settings_service(db, current_user.id)
    return service.get_edit_config(edit_model)


@router.put("/edit", response_model=EditConfigResponse)
async def update_edit_config(
    request: EditConfigUpdateRequest, edit_model: str = "qwen-image-max-edit", db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """Update edit configuration for a specific edit model."""
    service = get_settings_service(db, current_user.id)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    return service.set_edit_config(update, edit_model)


@router.post("/edit/reset", response_model=EditConfigResponse)
async def reset_edit_config(edit_model: str = "qwen-image-max-edit", db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reset edit configuration to defaults."""
    service = get_settings_service(db, current_user.id)
    service.delete_setting(f"edit_config:{edit_model}")
    return DEFAULT_EDIT_CONFIGS.get(edit_model, {})
