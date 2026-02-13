"""Add sync_enabled column to users table.

Revision ID: 018_sync_enabled
Revises: 017_users
"""
import sqlalchemy as sa
from alembic import op

revision = "018_sync_enabled"
down_revision = "017_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("sync_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("users", "sync_enabled")
