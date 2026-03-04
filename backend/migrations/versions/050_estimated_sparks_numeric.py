"""Change cost_decisions.estimated_sparks from INTEGER to NUMERIC(10,2).

Allows fractional spark estimates (e.g. 1.35 instead of 2) so estimates
are closer to actual costs.  Balance/transaction columns stay INTEGER.

Revision ID: 050_estimated_sparks_numeric
Revises: 049_usage_decision_unique
Create Date: 2026-03-03
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "050_estimated_sparks_numeric"
down_revision: Union[str, None] = "049_usage_decision_unique"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.alter_column(
        "cost_decisions",
        "estimated_sparks",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 2),
        existing_nullable=True,
        postgresql_using="estimated_sparks::numeric(10,2)",
    )


def downgrade() -> None:
    op.alter_column(
        "cost_decisions",
        "estimated_sparks",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="estimated_sparks::integer",
    )
