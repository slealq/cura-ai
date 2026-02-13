"""Add pair_type column to evaluation_pairs.

Revision ID: 016_pair_type
Revises: 015_lora_evaluations
"""
import sqlalchemy as sa
from alembic import op

revision = "016_pair_type"
down_revision = "015_lora_evaluations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evaluation_pairs",
        sa.Column("pair_type", sa.String(32), nullable=False, server_default="reference"),
    )


def downgrade() -> None:
    op.drop_column("evaluation_pairs", "pair_type")
