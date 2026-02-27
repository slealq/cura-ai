"""Add reserved_sparks to user_balance and cost_decisions.

Revision ID: 046_add_reserved_sparks
Revises: 045_integer_sparks
Create Date: 2026-02-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "046_add_reserved_sparks"
down_revision: Union[str, None] = "045_integer_sparks"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column(
        "user_balance",
        sa.Column("reserved_sparks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "cost_decisions",
        sa.Column("reserved_sparks", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cost_decisions", "reserved_sparks")
    op.drop_column("user_balance", "reserved_sparks")
