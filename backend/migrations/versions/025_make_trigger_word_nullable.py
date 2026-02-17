"""Make trigger_word nullable on lora_models.

Revision ID: 025_make_trigger_word_nullable
Revises: 024_add_cover_thumbnail_uri
"""
from typing import Sequence, Union

from alembic import op

revision: str = "025_make_trigger_word_nullable"
down_revision: Union[str, None] = "024_add_cover_thumbnail_uri"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("lora_models", "trigger_word", nullable=True)


def downgrade() -> None:
    # Backfill NULLs with the model name before restoring NOT NULL
    op.execute("UPDATE lora_models SET trigger_word = name WHERE trigger_word IS NULL")
    op.alter_column("lora_models", "trigger_word", nullable=False)
