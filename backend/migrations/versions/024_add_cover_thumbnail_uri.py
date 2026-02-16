"""Add cover_thumbnail_uri to folders and clusters.

Revision ID: 024_add_cover_thumbnail_uri
Revises: 023_add_cover_image
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "024_add_cover_thumbnail_uri"
down_revision: Union[str, None] = "023_add_cover_image"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "folders",
        sa.Column("cover_thumbnail_uri", sa.String(512), nullable=True),
    )
    op.add_column(
        "clusters",
        sa.Column("cover_thumbnail_uri", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("clusters", "cover_thumbnail_uri")
    op.drop_column("folders", "cover_thumbnail_uri")
