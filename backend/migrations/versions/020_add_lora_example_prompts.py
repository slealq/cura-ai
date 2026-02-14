"""Add example_prompts column to lora_models.

Revision ID: 020_example_prompts
Revises: 019_lora_weights
"""
import sqlalchemy as sa
from alembic import op

revision = "020_example_prompts"
down_revision = "019_lora_weights"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lora_models", sa.Column("example_prompts", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("lora_models", "example_prompts")
