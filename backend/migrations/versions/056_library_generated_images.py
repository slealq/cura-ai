"""Make finished generations and edits part of the image library.

Adds the ``generated`` and ``edited`` image sources and ``images.generated_image_id``
linking a library copy back to the generation it came from. Existing generations
are copied into the library by ``scripts/backfill_generated_library.py`` (it needs
storage access, so it is not part of this migration).

Revision ID: 056_library_generated_images
Revises: 055_refresh_model_catalog
Create Date: 2026-10-30
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "056_library_generated_images"
down_revision: Union[str, None] = "055_refresh_model_catalog"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # New enum values must be committed before any statement can use them
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE imagesource ADD VALUE IF NOT EXISTS 'generated'")
        op.execute("ALTER TYPE imagesource ADD VALUE IF NOT EXISTS 'edited'")

    op.add_column("images", sa.Column("generated_image_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_images_generated_image_id",
        "images",
        "generated_images",
        ["generated_image_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_images_generated_image_id", "images", ["generated_image_id"])


def downgrade() -> None:
    op.drop_index("ix_images_generated_image_id", table_name="images")
    op.drop_constraint("fk_images_generated_image_id", "images", type_="foreignkey")
    op.drop_column("images", "generated_image_id")
    # PostgreSQL cannot drop enum values; 'generated'/'edited' remain unused
