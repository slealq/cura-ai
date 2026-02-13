"""Convert preset prompts to guidance-only (strip system format wrappers).

Revision ID: 007_convert_prompts_to_guidance
Revises: 006_add_prompt_presets
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "007_convert_prompts_to_guidance"
down_revision = "006_add_prompt_presets"
branch_labels = None
depends_on = None

# New guidance-only defaults
NEW_DEFAULT_TAG_GUIDANCE = """Tags should categorize the image across these dimensions:
- Framing: full-body, upper-body, lower-body, feet-close-up, face-close-up, hands-close-up, medium-shot, wide-shot
- People: single-woman, single-man, multiple-people, couple, group
- Clothing: nude, semi-nude, clothed, lingerie, swimwear, dress, casual, formal, heels, barefoot
- Body features: soles-visible, toenails-visible, fingernails-visible, tattoos, piercings
- Activity: standing, sitting, lying-down, walking, posing, kneeling, bending-over
- Setting: indoor, outdoor, studio, bedroom, bathroom, beach, nature, urban
- Content: portrait, candid, artistic, professional, selfie, mirror

Only include tags that are clearly present or relevant."""

NEW_DEFAULT_DESC_GUIDANCE = """Analyze this image and provide a detailed description organized by sections. The goal is that if someone uses this description to generate an image via AI, the result should match the original image as closely as possible.

Sections to cover (include all that are relevant):

**Subject**: Person(s) - clothing, pose, position of hands and legs, action, body position and orientation.

**Face & Hair**: Hair style, color, length. Facial expression, makeup, notable features.

**Body Details**: Nails (fingers/toes) - colors, shape, length. Accessories, jewelry, tattoos.

**Camera**: Camera angle, distance, perspective relative to subject. Framing (close-up, medium shot, full body).

**Background**: Setting description, colors, objects, depth of field.

**Lighting**: Quality, direction, color temperature, shadows.

**Special Focus**: If the image emphasizes feet, describe feet in detail - toenails, nail colors, nail shapes, sole visibility, toe positioning. If adult content, describe what is visible, body positioning, and physical details explicitly.

Be specific, observational, and thorough. Write in plain descriptive language. The description should be long and detailed enough to reproduce the image."""


def strip_tag_format(prompt: str) -> str:
    """Strip known system format wrappers from a tag prompt, keeping only guidance."""
    text = prompt.strip()

    # Remove known opening paragraphs
    text = re.sub(
        r'^Analyze this image and return a JSON object[^\n]*\n*',
        '', text,
    )
    text = re.sub(
        r'^Return ONLY a valid JSON object[^\n]*\n*',
        '', text,
    )

    # Remove trailing JSON example block: { "tags": [...] }
    text = re.sub(
        r'\n*\{\s*\n?\s*"tags"\s*:\s*\[.*?\]\s*\n?\s*\}\s*$',
        '', text, flags=re.DOTALL,
    )

    result = text.strip()
    return result if result else prompt.strip()


def strip_description_format(prompt: str) -> str:
    """Strip known system format wrappers from a description prompt."""
    text = prompt.strip()

    # Remove "Return as JSON:" and following JSON block
    text = re.sub(
        r'\n*Return as JSON:\s*\n\{.*?\}\s*$',
        '', text, flags=re.DOTALL,
    )
    # Also handle "Return ONLY a valid JSON object..." variant
    text = re.sub(
        r'\n*Return ONLY a valid JSON object[^\n]*\n\{.*?\}\s*$',
        '', text, flags=re.DOTALL,
    )

    result = text.strip()
    return result if result else prompt.strip()


def upgrade() -> None:
    conn = op.get_bind()

    # Fetch all presets
    rows = conn.execute(
        sa.text("SELECT id, name, tag_prompt, description_prompt FROM prompt_presets")
    ).fetchall()

    for row in rows:
        preset_id, name, tag_prompt, desc_prompt = row

        if name == "Default":
            # Replace with clean guidance-only defaults
            new_tag = NEW_DEFAULT_TAG_GUIDANCE
            new_desc = NEW_DEFAULT_DESC_GUIDANCE
        else:
            # Strip format wrappers from custom presets
            new_tag = strip_tag_format(tag_prompt)
            new_desc = strip_description_format(desc_prompt)

        conn.execute(
            sa.text(
                "UPDATE prompt_presets SET tag_prompt = :tag, description_prompt = :desc WHERE id = :id"
            ),
            {"tag": new_tag, "desc": new_desc, "id": preset_id},
        )


def downgrade() -> None:
    # Can't perfectly restore format wrappers, but this is acceptable
    pass
