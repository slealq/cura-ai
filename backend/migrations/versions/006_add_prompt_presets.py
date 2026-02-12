"""Add prompt_presets table and migrate existing prompts from app_settings.

Revision ID: 006_add_prompt_presets
Revises: 005_add_pipeline_logs
"""
from alembic import op
import sqlalchemy as sa

revision = "006_add_prompt_presets"
down_revision = "005_add_pipeline_logs"
branch_labels = None
depends_on = None

# Factory defaults (duplicated here so migration is self-contained)
DEFAULT_TAG_PROMPT = """Analyze this image and return a JSON object with a flat list of tags for categorization purposes.

Return ONLY a valid JSON object with a single key "tags" containing an array of relevant tags (lowercase, hyphenated for multi-word).

Tags should categorize the image across these dimensions:
- Framing: full-body, upper-body, lower-body, feet-close-up, face-close-up, hands-close-up, medium-shot, wide-shot
- People: single-woman, single-man, multiple-people, couple, group
- Clothing: nude, semi-nude, clothed, lingerie, swimwear, dress, casual, formal, heels, barefoot
- Body features: soles-visible, toenails-visible, fingernails-visible, tattoos, piercings
- Activity: standing, sitting, lying-down, walking, posing, kneeling, bending-over
- Setting: indoor, outdoor, studio, bedroom, bathroom, beach, nature, urban
- Content: portrait, candid, artistic, professional, selfie, mirror

Only include tags that are clearly present or relevant.

{
  "tags": ["tag-1", "tag-2", "tag-3"]
}"""

DEFAULT_DESCRIPTION_PROMPT = """Analyze this image and provide a detailed description organized by sections. The goal is that if someone uses this description to generate an image via AI, the result should match the original image as closely as possible.

Sections to cover (include all that are relevant):

**Subject**: Person(s) - clothing, pose, position of hands and legs, action, body position and orientation.

**Face & Hair**: Hair style, color, length. Facial expression, makeup, notable features.

**Body Details**: Nails (fingers/toes) - colors, shape, length. Accessories, jewelry, tattoos.

**Camera**: Camera angle, distance, perspective relative to subject. Framing (close-up, medium shot, full body).

**Background**: Setting description, colors, objects, depth of field.

**Lighting**: Quality, direction, color temperature, shadows.

**Special Focus**: If the image emphasizes feet, describe feet in detail - toenails, nail colors, nail shapes, sole visibility, toe positioning. If adult content, describe what is visible, body positioning, and physical details explicitly.

Be specific, observational, and thorough. Write in plain descriptive language. The description should be long and detailed enough to reproduce the image.

Return as JSON:
{
  "description": "## Subject\\n...\\n\\n## Face & Hair\\n...\\n\\n## Camera\\n..."
}"""


def upgrade() -> None:
    # Create the table
    op.create_table(
        "prompt_presets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(256), unique=True, nullable=False),
        sa.Column("tag_prompt", sa.Text(), nullable=False),
        sa.Column("description_prompt", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_prompt_presets_id", "prompt_presets", ["id"])
    op.create_index("ix_prompt_presets_name", "prompt_presets", ["name"])

    # Data migration: read existing custom prompts from app_settings
    conn = op.get_bind()
    custom_tag = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'tag_prompt'")
    ).scalar()
    custom_desc = conn.execute(
        sa.text("SELECT value FROM app_settings WHERE key = 'description_prompt'")
    ).scalar()

    has_custom = custom_tag is not None or custom_desc is not None

    # Always create a "Default" preset with factory defaults
    conn.execute(
        sa.text(
            "INSERT INTO prompt_presets (name, tag_prompt, description_prompt, is_default, created_at, updated_at) "
            "VALUES (:name, :tag, :desc, :is_default, NOW(), NOW())"
        ),
        {
            "name": "Default",
            "tag": DEFAULT_TAG_PROMPT,
            "desc": DEFAULT_DESCRIPTION_PROMPT,
            "is_default": not has_custom,
        },
    )

    # If custom prompts existed, create a migrated preset and make it active
    if has_custom:
        conn.execute(
            sa.text(
                "INSERT INTO prompt_presets (name, tag_prompt, description_prompt, is_default, created_at, updated_at) "
                "VALUES (:name, :tag, :desc, :is_default, NOW(), NOW())"
            ),
            {
                "name": "Custom (migrated)",
                "tag": custom_tag or DEFAULT_TAG_PROMPT,
                "desc": custom_desc or DEFAULT_DESCRIPTION_PROMPT,
                "is_default": True,
            },
        )

    # Clean up old keys from app_settings
    conn.execute(sa.text("DELETE FROM app_settings WHERE key IN ('tag_prompt', 'description_prompt')"))


def downgrade() -> None:
    # Migrate active preset back to app_settings
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT tag_prompt, description_prompt FROM prompt_presets WHERE is_default = true LIMIT 1")
    ).first()
    if row:
        conn.execute(
            sa.text(
                "INSERT INTO app_settings (key, value, description, created_at, updated_at) "
                "VALUES ('tag_prompt', :tag, 'Full prompt for image tagging', NOW(), NOW()), "
                "       ('description_prompt', :desc, 'Full prompt for image description generation', NOW(), NOW())"
            ),
            {"tag": row[0], "desc": row[1]},
        )

    op.drop_table("prompt_presets")
