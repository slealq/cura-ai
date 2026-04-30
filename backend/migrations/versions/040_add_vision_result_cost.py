"""Add charged_cost to vision_results.

Revision ID: 040_add_vision_result_cost
Revises: 039_add_embed_timing_columns
Create Date: 2026-02-25
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "040_add_vision_result_cost"
down_revision: Union[str, None] = "039_add_embed_timing_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vision_results",
        sa.Column("charged_cost", sa.Numeric(12, 6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vision_results", "charged_cost")
