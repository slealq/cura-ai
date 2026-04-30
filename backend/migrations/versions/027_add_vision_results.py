"""Add vision_results table for persisting vision analysis outputs.

Revision ID: 027_add_vision_results
Revises: 026_add_edit_job_types
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "027_add_vision_results"
down_revision: Union[str, None] = "026_add_edit_job_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vision_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_image_id", sa.Integer(), nullable=True),
        sa.Column("source_generated_id", sa.Integer(), nullable=True),
        sa.Column("source_object_key", sa.String(512), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("result_tags", sa.JSON(), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_image_id"], ["images.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_generated_id"], ["generated_images.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vision_results_id", "vision_results", ["id"])
    op.create_index("ix_vision_results_user_id", "vision_results", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_vision_results_user_id", table_name="vision_results")
    op.drop_index("ix_vision_results_id", table_name="vision_results")
    op.drop_table("vision_results")
