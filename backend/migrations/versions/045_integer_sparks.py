"""Add integer sparks columns for dual-write migration.

Revision ID: 045_integer_sparks
Revises: 044_debit_uniqueness
Create Date: 2026-02-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "045_integer_sparks"
down_revision: Union[str, None] = "044_debit_uniqueness"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # UserBalance: balance_sparks (integer mirror of Decimal balance)
    op.add_column(
        "user_balance",
        sa.Column("balance_sparks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE user_balance SET balance_sparks = ROUND(balance)")

    # BalanceTransaction: amount_sparks (integer mirror of Decimal amount)
    op.add_column(
        "balance_transactions",
        sa.Column("amount_sparks", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE balance_transactions SET amount_sparks = ROUND(amount)")

    # Job: charged_sparks (integer mirror of Decimal charged_cost, which is in sparks)
    op.add_column(
        "jobs",
        sa.Column("charged_sparks", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE jobs SET charged_sparks = ROUND(charged_cost) WHERE charged_cost IS NOT NULL"
    )

    # VisionResult: charged_sparks (charged_cost is in USD, convert via ×1000)
    op.add_column(
        "vision_results",
        sa.Column("charged_sparks", sa.Integer(), nullable=True),
    )
    op.execute(
        "UPDATE vision_results SET charged_sparks = ROUND(charged_cost * 1000) "
        "WHERE charged_cost IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("vision_results", "charged_sparks")
    op.drop_column("jobs", "charged_sparks")
    op.drop_column("balance_transactions", "amount_sparks")
    op.drop_column("user_balance", "balance_sparks")
