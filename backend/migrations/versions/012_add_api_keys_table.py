"""Add api_keys table.

Revision ID: 012_add_api_keys_table
Revises: 011_add_lora_and_generation
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "012_add_api_keys_table"
down_revision = "011_add_lora_and_generation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = inspect(conn)
    if "api_keys" not in inspector.get_table_names():
        op.create_table(
            "api_keys",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("provider", sa.String(32), unique=True, nullable=False),
            sa.Column("encrypted_key", sa.Text(), nullable=False),
            sa.Column("key_suffix", sa.String(8), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="unknown"),
            sa.Column("last_validated_at", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
    else:
        # Table exists (from create_all) — widen varchar columns to match our model
        op.alter_column("api_keys", "provider", type_=sa.String(32), existing_type=sa.String(9))
        op.alter_column("api_keys", "status", type_=sa.String(32), existing_type=sa.String(14))

    # Create index if not exists
    inspector = inspect(conn)
    existing_indexes = [idx["name"] for idx in inspector.get_indexes("api_keys")]
    if "ix_api_keys_provider_status" not in existing_indexes:
        op.create_index("ix_api_keys_provider_status", "api_keys", ["provider", "status"])


def downgrade() -> None:
    op.drop_index("ix_api_keys_provider_status", table_name="api_keys")
    op.drop_table("api_keys")
