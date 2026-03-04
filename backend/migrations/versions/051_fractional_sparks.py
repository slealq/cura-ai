"""Convert all sparks columns from INTEGER to NUMERIC(10,2).

Allows fractional sparks throughout the billing pipeline so sub-1-spark
operations (e.g. Grok 4 Fast tag at ~0.44 sparks) are correctly debited
instead of being truncated to 0.

Affected columns:
  - usage_records.delta_sparks
  - user_balance.balance_sparks
  - user_balance.reserved_sparks
  - balance_transactions.amount_sparks
  - cost_decisions.reserved_sparks
  - jobs.charged_sparks
  - vision_results.charged_sparks

Revision ID: 051_fractional_sparks
Revises: 050_estimated_sparks_numeric
Create Date: 2026-03-03
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "051_fractional_sparks"
down_revision: Union[str, None] = "050_estimated_sparks_numeric"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

_COLUMNS = [
    ("usage_records", "delta_sparks"),
    ("user_balance", "balance_sparks"),
    ("user_balance", "reserved_sparks"),
    ("balance_transactions", "amount_sparks"),
    ("cost_decisions", "reserved_sparks"),
    ("jobs", "charged_sparks"),
    ("vision_results", "charged_sparks"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Integer(),
            type_=sa.Numeric(10, 2),
            existing_nullable=True,
            postgresql_using=f"{column}::numeric(10,2)",
        )


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(10, 2),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using=f"{column}::integer",
        )
