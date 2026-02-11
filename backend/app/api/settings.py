"""Settings API endpoints."""
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import get_db
from app.services.settings_service import get_settings_service

logger = logging.getLogger(__name__)
app_settings = get_settings()
router = APIRouter(prefix="/settings", tags=["settings"])


class GuidanceSettingsRequest(BaseModel):
    """Request to update guidance settings."""

    description_guidance: str | None = None
    tag_guidance: str | None = None


class GuidanceSettingsResponse(BaseModel):
    """Response with current guidance settings."""

    description_guidance: str | None = None
    tag_guidance: str | None = None


class GuidanceSuggestRequest(BaseModel):
    """Request to get AI-suggested guidance edits."""

    current_guidance: str
    change_request: str
    guidance_type: Literal["description", "tag"]


class GuidanceSuggestResponse(BaseModel):
    """Response with suggested guidance text."""

    suggested_guidance: str


@router.get("/guidance", response_model=GuidanceSettingsResponse)
async def get_guidance_settings(db: Session = Depends(get_db)):
    """Get current default guidance settings."""
    settings_service = get_settings_service(db)
    return GuidanceSettingsResponse(
        description_guidance=settings_service.get_default_description_guidance(),
        tag_guidance=settings_service.get_default_tag_guidance(),
    )


@router.put("/guidance", response_model=GuidanceSettingsResponse)
async def update_guidance_settings(
    request: GuidanceSettingsRequest, db: Session = Depends(get_db)
):
    """Update default guidance settings."""
    settings_service = get_settings_service(db)

    if request.description_guidance is not None:
        settings_service.set_default_description_guidance(request.description_guidance)

    if request.tag_guidance is not None:
        settings_service.set_default_tag_guidance(request.tag_guidance)

    return GuidanceSettingsResponse(
        description_guidance=settings_service.get_default_description_guidance(),
        tag_guidance=settings_service.get_default_tag_guidance(),
    )


@router.post("/guidance/suggest", response_model=GuidanceSuggestResponse)
async def suggest_guidance(request: GuidanceSuggestRequest):
    """Use AI to suggest edits to guidance text based on a change request."""
    try:
        client = AsyncOpenAI(api_key=app_settings.openai_api_key)

        system_prompt = (
            f"You are helping edit AI guidance text for image {request.guidance_type} generation. "
            "The user will provide the current guidance and a requested change. "
            "Return ONLY the new complete guidance text incorporating the requested changes. "
            "Do not include any explanation or commentary, just the updated guidance text."
        )

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Current guidance:\n{request.current_guidance}\n\n"
                        f"Requested change:\n{request.change_request}"
                    ),
                },
            ],
            max_tokens=2000,
        )

        suggested = response.choices[0].message.content or ""
        return GuidanceSuggestResponse(suggested_guidance=suggested.strip())

    except Exception as e:
        logger.error(f"Failed to suggest guidance: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate suggestion: {str(e)}")
