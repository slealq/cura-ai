"""Settings API endpoints."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import get_db
from app.services.settings_service import (
    DEFAULT_DESCRIPTION_PROMPT,
    DEFAULT_TAG_PROMPT,
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
