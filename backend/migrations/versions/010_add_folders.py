"""Add folders and folder_images tables.

Revision ID: 010_add_folders
Revises: 009_add_search_vector
"""
import sqlalchemy as sa
from alembic import op

revision = "010_add_folders"
down_revision = "009_add_search_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "folders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "folder_images",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("folder_id", sa.Integer(), sa.ForeignKey("folders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("folder_id", "image_id", name="uq_folder_image"),
    )

    op.create_index("ix_folder_images_folder_id", "folder_images", ["folder_id"])
    op.create_index("ix_folder_images_image_id", "folder_images", ["image_id"])


def downgrade() -> None:
    op.drop_index("ix_folder_images_image_id", table_name="folder_images")
    op.drop_index("ix_folder_images_folder_id", table_name="folder_images")
    op.drop_table("folder_images")
    op.drop_table("folders")
