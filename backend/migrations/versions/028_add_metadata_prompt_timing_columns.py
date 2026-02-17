"""Add prompt text and timing columns to image_metadata, add batch_describe job type.

Revision ID: 028_add_prompt_timing
Revises: 027_add_vision_results
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "028_add_prompt_timing"
down_revision: Union[str, None] = "027_add_vision_results"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to image_metadata
    op.add_column("image_metadata", sa.Column("tag_prompt_text", sa.Text(), nullable=True))
    op.add_column("image_metadata", sa.Column("description_prompt_text", sa.Text(), nullable=True))
    op.add_column("image_metadata", sa.Column("tagged_at", sa.DateTime(), nullable=True))
    op.add_column("image_metadata", sa.Column("described_at", sa.DateTime(), nullable=True))
    op.add_column("image_metadata", sa.Column("tagging_duration_ms", sa.Integer(), nullable=True))
    op.add_column("image_metadata", sa.Column("caption_duration_ms", sa.Integer(), nullable=True))

    # Add batch_describe to jobtype enum
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'batch_describe'")


def downgrade() -> None:
    op.drop_column("image_metadata", "caption_duration_ms")
    op.drop_column("image_metadata", "tagging_duration_ms")
    op.drop_column("image_metadata", "described_at")
    op.drop_column("image_metadata", "tagged_at")
    op.drop_column("image_metadata", "description_prompt_text")
    op.drop_column("image_metadata", "tag_prompt_text")
    # Note: PostgreSQL does not support removing enum values
