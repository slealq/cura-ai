"""Settings API endpoints."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import get_db
from app.models.api_key import APIKeyStatus, APIProvider
from app.services.api_key_service import get_api_key_service
from app.services.settings_service import (
    DEFAULT_CLUSTERING_CONFIG,
    DEFAULT_DESCRIPTION_PROMPT,
    DEFAULT_GENERATION_CONFIG,
    DEFAULT_PROVIDER_CONFIG,
    DEFAULT_TAG_PROMPT,
    DEFAULT_TRAINING_CONFIG,
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


class ProviderConfigUpdateRequest(BaseModel):
    """Partial update for provider configuration."""

    vision_provider: str | None = None
    embedding_provider: str | None = None
    openai_vision_model: str | None = None
    openai_embedding_model: str | None = None
    anthropic_vision_model: str | None = None


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
async def list_presets(db: Session = Depends(get_db)):
    """List all prompt presets."""
    service = get_settings_service(db)
    return [_preset_to_response(p) for p in service.list_presets()]


@router.post("/presets", response_model=PresetResponse, status_code=201)
async def create_preset(request: PresetCreateRequest, db: Session = Depends(get_db)):
    """Create a new prompt preset."""
    service = get_settings_service(db)
    try:
        preset = service.create_preset(request.name, request.tag_prompt, request.description_prompt)
    except Exception:
        raise HTTPException(status_code=400, detail="A preset with that name already exists")
    return _preset_to_response(preset)


@router.get("/presets/{preset_id}", response_model=PresetResponse)
async def get_preset(preset_id: int, db: Session = Depends(get_db)):
    """Get a single preset by ID."""
    service = get_settings_service(db)
    preset = service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _preset_to_response(preset)


@router.put("/presets/{preset_id}", response_model=PresetResponse)
async def update_preset(preset_id: int, request: PresetUpdateRequest, db: Session = Depends(get_db)):
    """Update a preset's name and/or prompts."""
    service = get_settings_service(db)
    preset = service.update_preset(preset_id, name=request.name, tag_prompt=request.tag_prompt, description_prompt=request.description_prompt)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _preset_to_response(preset)


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    """Delete a preset (cannot delete the active preset)."""
    service = get_settings_service(db)
    preset = service.get_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    if not service.delete_preset(preset_id):
        raise HTTPException(status_code=403, detail="Cannot delete the active preset")


@router.post("/presets/{preset_id}/activate", response_model=PresetResponse)
async def activate_preset(preset_id: int, db: Session = Depends(get_db)):
    """Set a preset as the active default."""
    service = get_settings_service(db)
    preset = service.set_default_preset(preset_id)
    if not preset:
        raise HTTPException(status_code=404, detail="Preset not found")
    return _preset_to_response(preset)


# --- Legacy prompt endpoints (backward compat, operate on active preset) ---


@router.get("/prompts", response_model=PromptSettingsResponse)
async def get_prompt_settings(db: Session = Depends(get_db)):
    """Get current default prompt settings."""
    settings_service = get_settings_service(db)
    active = settings_service._ensure_default_preset()
    return PromptSettingsResponse(
        description_prompt=active.description_prompt,
        tag_prompt=active.tag_prompt,
        description_prompt_custom=active.description_prompt != DEFAULT_DESCRIPTION_PROMPT,
        tag_prompt_custom=active.tag_prompt != DEFAULT_TAG_PROMPT,
    )


@router.put("/prompts", response_model=PromptSettingsResponse)
async def update_prompt_settings(
    request: PromptSettingsRequest, db: Session = Depends(get_db)
):
    """Update active preset's prompts."""
    settings_service = get_settings_service(db)
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
):
    """Reset active preset's prompts to factory defaults."""
    settings_service = get_settings_service(db)
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
async def suggest_prompt(request: PromptSuggestRequest):
    """Use AI to suggest edits to a prompt based on a change request."""
    try:
        client = AsyncOpenAI(api_key=app_settings.openai_api_key)

        system_prompt = (
            f"You are helping edit an AI prompt for image {request.prompt_type} generation. "
            "The user will provide the current prompt and a requested change. "
            "Return ONLY the new complete prompt incorporating the requested changes. "
            "Do not include any explanation or commentary, just the updated prompt text."
        )

        response = await client.chat.completions.create(
            model="gpt-4o",
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
            max_tokens=2000,
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


@router.get("/api-keys", response_model=list[APIKeyResponse])
async def list_api_keys(db: Session = Depends(get_db)):
    """List all stored API keys (returns metadata only, never the actual key)."""
    service = get_api_key_service(db)
    keys = service.get_all_keys()

    # Build response including providers with no stored key
    stored = {k.provider: k for k in keys}
    result = []
    for provider in APIProvider:
        if provider.value in stored:
            result.append(_api_key_to_response(stored[provider.value]))
        else:
            # Check if env var is set
            settings = get_settings()
            env_keys = {
                "openai": settings.openai_api_key,
                "anthropic": settings.anthropic_api_key,
                "fal": settings.fal_api_key,
            }
            env_key = env_keys.get(provider.value, "")
            if env_key:
                result.append(APIKeyResponse(
                    provider=provider.value,
                    key_suffix=env_key[-4:] if len(env_key) >= 4 else None,
                    status="active",
                    last_validated_at=None,
                    last_error=None,
                ))
            else:
                result.append(APIKeyResponse(
                    provider=provider.value,
                    key_suffix=None,
                    status="not_set",
                    last_validated_at=None,
                    last_error=None,
                ))
    return result


@router.put("/api-keys/{provider}", response_model=APIKeyResponse)
async def save_api_key(provider: str, request: APIKeySaveRequest, db: Session = Depends(get_db)):
    """Save or update an API key (validates first)."""
    try:
        api_provider = APIProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    service = get_api_key_service(db)
    api_key, result = await service.validate_and_save_key(api_provider, request.key)
    return _api_key_to_response(api_key)


@router.delete("/api-keys/{provider}", status_code=204)
async def delete_api_key(provider: str, db: Session = Depends(get_db)):
    """Remove a stored API key."""
    try:
        api_provider = APIProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    service = get_api_key_service(db)
    if not service.delete_key(api_provider):
        raise HTTPException(status_code=404, detail="No stored key for this provider")


@router.post("/api-keys/{provider}/validate", response_model=APIKeyResponse)
async def validate_api_key(provider: str, db: Session = Depends(get_db)):
    """Re-validate an existing stored key."""
    try:
        api_provider = APIProvider(provider)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    service = get_api_key_service(db)
    key_value = service.resolve_key(api_provider)
    if not key_value:
        raise HTTPException(status_code=404, detail="No key configured for this provider")

    api_key, result = await service.validate_and_save_key(api_provider, key_value)
    return _api_key_to_response(api_key)


# --- Provider config endpoints ---


@router.get("/providers", response_model=ProviderConfigResponse)
async def get_provider_config(db: Session = Depends(get_db)):
    """Get current provider configuration."""
    service = get_settings_service(db)
    return service.get_provider_config()


@router.put("/providers", response_model=ProviderConfigResponse)
async def update_provider_config(
    request: ProviderConfigUpdateRequest, db: Session = Depends(get_db)
):
    """Update provider configuration (partial update, merges with defaults)."""
    service = get_settings_service(db)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    return service.set_provider_config(update)


@router.post("/providers/reset", response_model=ProviderConfigResponse)
async def reset_provider_config(db: Session = Depends(get_db)):
    """Reset provider configuration to defaults."""
    service = get_settings_service(db)
    service.delete_setting("provider_config")
    return DEFAULT_PROVIDER_CONFIG


# --- Model discovery endpoint ---


@router.get("/models/{provider}", response_model=list[ProviderModelInfo])
async def get_provider_models(provider: str, db: Session = Depends(get_db)):
    """Get available models for a provider."""
    if provider == "openai":
        return await _get_openai_models(db)
    elif provider == "anthropic":
        return _get_anthropic_models()
    elif provider == "fal":
        return _get_fal_models()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")


async def _get_openai_models(db: Session) -> list[ProviderModelInfo]:
    """Fetch available OpenAI models via API."""
    from app.services.api_key_service import get_api_key_service as get_aks

    key_service = get_aks(db)
    api_key = key_service.resolve_key(APIProvider.OPENAI)
    if not api_key:
        # Return known defaults if no key available
        return [
            ProviderModelInfo(id="gpt-4o", name="GPT-4o", capabilities=["vision", "chat"]),
            ProviderModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", capabilities=["vision", "chat"]),
            ProviderModelInfo(id="text-embedding-3-small", name="Text Embedding 3 Small", capabilities=["embedding"]),
            ProviderModelInfo(id="text-embedding-3-large", name="Text Embedding 3 Large", capabilities=["embedding"]),
        ]

    try:
        client = AsyncOpenAI(api_key=api_key)
        models_resp = await client.models.list()
        result = []
        for m in models_resp.data:
            mid = m.id
            # Vision-capable models
            if any(mid.startswith(p) for p in ("gpt-4o", "gpt-4.1", "gpt-4.5", "gpt-5", "chatgpt-4o")):
                if "audio" in mid or "realtime" in mid or "transcribe" in mid or "tts" in mid:
                    continue
                caps = ["vision", "chat"]
                name = mid.replace("-", " ").title()
                result.append(ProviderModelInfo(id=mid, name=name, capabilities=caps))
            # Embedding models
            elif mid.startswith("text-embedding-"):
                result.append(ProviderModelInfo(
                    id=mid,
                    name=mid.replace("-", " ").title(),
                    capabilities=["embedding"],
                ))
        # Sort: vision models first, then embedding
        result.sort(key=lambda x: (0 if "vision" in x.capabilities else 1, x.id))
        return result if result else [
            ProviderModelInfo(id="gpt-4o", name="GPT-4o", capabilities=["vision", "chat"]),
            ProviderModelInfo(id="text-embedding-3-small", name="Text Embedding 3 Small", capabilities=["embedding"]),
        ]
    except Exception as e:
        logger.warning(f"Failed to fetch OpenAI models: {e}")
        return [
            ProviderModelInfo(id="gpt-4o", name="GPT-4o", capabilities=["vision", "chat"]),
            ProviderModelInfo(id="gpt-4o-mini", name="GPT-4o Mini", capabilities=["vision", "chat"]),
            ProviderModelInfo(id="text-embedding-3-small", name="Text Embedding 3 Small", capabilities=["embedding"]),
            ProviderModelInfo(id="text-embedding-3-large", name="Text Embedding 3 Large", capabilities=["embedding"]),
        ]


def _get_anthropic_models() -> list[ProviderModelInfo]:
    """Return curated list of Anthropic Claude models with vision support."""
    return [
        ProviderModelInfo(id="claude-sonnet-4-20250514", name="Claude Sonnet 4", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="claude-haiku-4-20250414", name="Claude Haiku 4", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="claude-3-5-sonnet-20241022", name="Claude 3.5 Sonnet", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="claude-3-5-haiku-20241022", name="Claude 3.5 Haiku", capabilities=["vision", "chat"]),
        ProviderModelInfo(id="claude-3-haiku-20240307", name="Claude 3 Haiku", capabilities=["vision", "chat"]),
    ]


def _get_fal_models() -> list[ProviderModelInfo]:
    """Return supported fal.ai endpoints."""
    return [
        ProviderModelInfo(id="fal-ai/flux/dev", name="Flux.1 Dev", capabilities=["generation"]),
        ProviderModelInfo(id="fal-ai/flux-lora", name="Flux LoRA", capabilities=["generation", "lora"]),
        ProviderModelInfo(id="fal-ai/flux-lora-fast-training", name="Flux LoRA Fast Training", capabilities=["training"]),
    ]


# --- Clustering config endpoints ---


@router.get("/clustering", response_model=ClusteringConfigResponse)
async def get_clustering_config(db: Session = Depends(get_db)):
    """Get current clustering configuration."""
    service = get_settings_service(db)
    return service.get_clustering_config()


@router.put("/clustering", response_model=ClusteringConfigResponse)
async def update_clustering_config(
    request: ClusteringConfigUpdateRequest, db: Session = Depends(get_db)
):
    """Update clustering configuration (partial update, merges with defaults)."""
    service = get_settings_service(db)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    config = service.set_clustering_config(update)
    return config


@router.post("/clustering/reset", response_model=ClusteringConfigResponse)
async def reset_clustering_config(db: Session = Depends(get_db)):
    """Reset clustering configuration to defaults."""
    service = get_settings_service(db)
    service.delete_setting("clustering_config")
    return DEFAULT_CLUSTERING_CONFIG


# --- Generation config endpoints ---


class GenerationConfigResponse(BaseModel):
    """Current generation configuration."""

    base_model: str
    width: int
    height: int
    num_inference_steps: int
    guidance_scale: float
    default_lora_scale: float


class GenerationConfigUpdateRequest(BaseModel):
    """Partial update for generation configuration."""

    base_model: str | None = None
    width: int | None = None
    height: int | None = None
    num_inference_steps: int | None = None
    guidance_scale: float | None = None
    default_lora_scale: float | None = None


@router.get("/generation", response_model=GenerationConfigResponse)
async def get_generation_config(db: Session = Depends(get_db)):
    """Get current generation configuration."""
    service = get_settings_service(db)
    return service.get_generation_config()


@router.put("/generation", response_model=GenerationConfigResponse)
async def update_generation_config(
    request: GenerationConfigUpdateRequest, db: Session = Depends(get_db)
):
    """Update generation configuration."""
    service = get_settings_service(db)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    return service.set_generation_config(update)


@router.post("/generation/reset", response_model=GenerationConfigResponse)
async def reset_generation_config(db: Session = Depends(get_db)):
    """Reset generation configuration to defaults."""
    service = get_settings_service(db)
    service.delete_setting("generation_config")
    return DEFAULT_GENERATION_CONFIG


# --- Training config endpoints ---


class TrainingConfigResponse(BaseModel):
    """Current training configuration."""

    steps: int
    is_style: bool


class TrainingConfigUpdateRequest(BaseModel):
    """Partial update for training configuration."""

    steps: int | None = None
    is_style: bool | None = None


@router.get("/training", response_model=TrainingConfigResponse)
async def get_training_config(db: Session = Depends(get_db)):
    """Get current training configuration."""
    service = get_settings_service(db)
    return service.get_training_config()


@router.put("/training", response_model=TrainingConfigResponse)
async def update_training_config(
    request: TrainingConfigUpdateRequest, db: Session = Depends(get_db)
):
    """Update training configuration."""
    service = get_settings_service(db)
    update = {k: v for k, v in request.model_dump().items() if v is not None}
    return service.set_training_config(update)


@router.post("/training/reset", response_model=TrainingConfigResponse)
async def reset_training_config(db: Session = Depends(get_db)):
    """Reset training configuration to defaults."""
    service = get_settings_service(db)
    service.delete_setting("training_config")
    return DEFAULT_TRAINING_CONFIG
