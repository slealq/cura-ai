"""Add folder_delete to jobtype enum.

Revision ID: 022_add_folder_delete
Revises: 021_fix_enum_case
"""
from typing import Sequence, Union

from alembic import op

revision: str = "022_add_folder_delete"
down_revision: Union[str, None] = "021_fix_enum_case"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'folder_delete'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; this is a no-op.
    pass
