"""Add edit_image and batch_edit job types.

Revision ID: 026_add_edit_job_types
Revises: 025_make_trigger_word_nullable
"""
from typing import Sequence, Union

from alembic import op

revision: str = "026_add_edit_job_types"
down_revision: Union[str, None] = "025_make_trigger_word_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'edit_image'")
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'batch_edit'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op
    pass
