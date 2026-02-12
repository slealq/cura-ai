"""Add cluster_id column to lora_models table.

Revision ID: 014_lora_cluster_id
Revises: 013_fix_jobtype_enum_case
"""
import sqlalchemy as sa
from alembic import op

revision = "014_lora_cluster_id"
down_revision = "013_fix_jobtype_enum_case"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "lora_models",
        sa.Column("cluster_id", sa.Integer(), sa.ForeignKey("clusters.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_lora_models_cluster_id", "lora_models", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_lora_models_cluster_id", table_name="lora_models")
    op.drop_column("lora_models", "cluster_id")
