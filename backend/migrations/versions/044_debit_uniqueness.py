"""Add partial unique index on balance_transactions for debit idempotency.

Revision ID: 044_debit_uniqueness
Revises: 043_cost_decisions
Create Date: 2026-02-26
"""
from typing import Union

from alembic import op

revision: str = "044_debit_uniqueness"
down_revision: Union[str, None] = "043_cost_decisions"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Partial unique index: prevents duplicate debits for the same usage record.
    # NULLs are treated as distinct by PostgreSQL, so combined job debits
    # (reference_id=NULL) are unaffected.
    op.create_index(
        "uq_balance_transactions_debit_reference",
        "balance_transactions",
        ["user_id", "reference_id"],
        unique=True,
        postgresql_where="reference_id IS NOT NULL AND transaction_type = 'debit'",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_balance_transactions_debit_reference",
        table_name="balance_transactions",
    )
