"""Add detail JSON column to usage_records and created_at index.

Revision ID: 033_add_usage_record_detail
Revises: 032_add_gpt5_pricing
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON

revision: str = "033_add_usage_record_detail"
down_revision: Union[str, None] = "032_add_gpt5_pricing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usage_records", sa.Column("detail", JSON, nullable=True))
    op.create_index(
        "ix_usage_records_created_at_desc",
        "usage_records",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_created_at_desc", table_name="usage_records")
    op.drop_column("usage_records", "detail")
