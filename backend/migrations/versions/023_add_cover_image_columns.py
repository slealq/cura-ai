"""Add cover_image_id to folders and clusters.

Revision ID: 023_add_cover_image
Revises: 022_add_folder_delete
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023_add_cover_image"
down_revision: Union[str, None] = "022_add_folder_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add cover_image_id to folders
    op.add_column(
        "folders",
        sa.Column(
            "cover_image_id",
            sa.Integer(),
            sa.ForeignKey("images.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_folders_cover_image_id", "folders", ["cover_image_id"])

    # Add cover_image_id to clusters
    op.add_column(
        "clusters",
        sa.Column(
            "cover_image_id",
            sa.Integer(),
            sa.ForeignKey("images.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_clusters_cover_image_id", "clusters", ["cover_image_id"])

    # Backfill folders: pick most recently added image per folder
    op.execute("""
        UPDATE folders f
        SET cover_image_id = sub.image_id
        FROM (
            SELECT DISTINCT ON (folder_id) folder_id, image_id
            FROM folder_images
            ORDER BY folder_id, added_at DESC
        ) sub
        WHERE f.id = sub.folder_id
    """)

    # Backfill clusters: pick first representative_image_ids element that still exists
    op.execute("""
        UPDATE clusters c
        SET cover_image_id = sub.img_id
        FROM (
            SELECT c2.id AS cluster_id, (c2.representative_image_ids->>0)::int AS img_id
            FROM clusters c2
            WHERE c2.representative_image_ids IS NOT NULL
              AND json_array_length(c2.representative_image_ids) > 0
        ) sub
        JOIN images i ON i.id = sub.img_id
        WHERE c.id = sub.cluster_id
    """)


def downgrade() -> None:
    op.drop_index("ix_clusters_cover_image_id", table_name="clusters")
    op.drop_column("clusters", "cover_image_id")
    op.drop_index("ix_folders_cover_image_id", table_name="folders")
    op.drop_column("folders", "cover_image_id")
