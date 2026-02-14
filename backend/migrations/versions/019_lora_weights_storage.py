"""Add LoRA weights storage columns.

Revision ID: 019_lora_weights
Revises: 018_sync_enabled
"""
import sqlalchemy as sa
from alembic import op

revision = "019_lora_weights"
down_revision = "018_sync_enabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lora_models", sa.Column("weights_object_key", sa.String(256), nullable=True))
    op.add_column("lora_models", sa.Column("file_size", sa.Integer(), nullable=True))
    op.add_column("lora_models", sa.Column("file_hash", sa.String(64), nullable=True))
    op.add_column("lora_models", sa.Column("weights_downloaded_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("lora_models", "weights_downloaded_at")
    op.drop_column("lora_models", "file_hash")
    op.drop_column("lora_models", "file_size")
    op.drop_column("lora_models", "weights_object_key")
