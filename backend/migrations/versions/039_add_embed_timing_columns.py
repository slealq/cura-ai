"""Add embedded_at and embedding_duration_ms to image_metadata.

Revision ID: 039_add_embed_timing_columns
Revises: 038_add_gemini_flash_pricing
Create Date: 2026-02-20
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "039_add_embed_timing_columns"
down_revision: Union[str, None] = "038_add_gemini_flash_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("image_metadata", sa.Column("embedded_at", sa.DateTime(), nullable=True))
    op.add_column("image_metadata", sa.Column("embedding_duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("image_metadata", "embedding_duration_ms")
    op.drop_column("image_metadata", "embedded_at")
