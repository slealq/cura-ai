"""Flatten tags to list, remove caption_short, rename description guidance.

Revision ID: 003_flatten_tags_remove_caption
Revises: 002_add_app_settings
Create Date: 2024-01-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = '003_flatten_tags_remove_caption'
down_revision: Union[str, None] = '002_add_app_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Flatten image_metadata.tags from {"cat": ["a","b"], ...} to ["a","b",...]
    conn.execute(text("""
        UPDATE image_metadata SET tags = (
            SELECT COALESCE(
                (SELECT jsonb_agg(DISTINCT val)
                 FROM jsonb_each(tags::jsonb) AS cat(key, arr),
                      jsonb_array_elements_text(arr) AS val),
                '[]'::jsonb
            )
        ) WHERE tags IS NOT NULL AND jsonb_typeof(tags::jsonb) = 'object'
    """))

    # 2. Drop caption_short column
    op.drop_column('image_metadata', 'caption_short')

    # 3. Flatten clusters.common_tags same way
    conn.execute(text("""
        UPDATE clusters SET common_tags = (
            SELECT COALESCE(
                (SELECT jsonb_agg(DISTINCT val)
                 FROM jsonb_each(common_tags::jsonb) AS cat(key, arr),
                      jsonb_array_elements_text(arr) AS val),
                '[]'::jsonb
            )
        ) WHERE common_tags IS NOT NULL AND jsonb_typeof(common_tags::jsonb) = 'object'
    """))

    # 4. Rename settings key
    conn.execute(text(
        "UPDATE app_settings SET key = 'default_description_guidance' "
        "WHERE key = 'default_caption_guidance'"
    ))


def downgrade() -> None:
    conn = op.get_bind()

    # Add caption_short back
    op.add_column('image_metadata', sa.Column('caption_short', sa.Text(), nullable=True))

    # Set tags to empty dict (cannot reconstruct categories)
    conn.execute(text(
        "UPDATE image_metadata SET tags = '{}'::jsonb "
        "WHERE tags IS NOT NULL AND jsonb_typeof(tags::jsonb) = 'array'"
    ))

    # Set common_tags to empty dict
    conn.execute(text(
        "UPDATE clusters SET common_tags = '{}'::jsonb "
        "WHERE common_tags IS NOT NULL AND jsonb_typeof(common_tags::jsonb) = 'array'"
    ))

    # Rename settings key back
    conn.execute(text(
        "UPDATE app_settings SET key = 'default_caption_guidance' "
        "WHERE key = 'default_description_guidance'"
    ))
