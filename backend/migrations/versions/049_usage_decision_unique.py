"""Add partial unique index on usage_records.cost_decision_id for idempotency.

Prevents duplicate UsageRecords for the same CostDecision (e.g. Celery retries).
Backfills by deleting duplicates, keeping the earliest per cost_decision_id.

Revision ID: 049_usage_decision_unique
Revises: 048_fix_flux_2_pro_model_name
Create Date: 2026-03-03
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "049_usage_decision_unique"
down_revision: Union[str, None] = "048_fix_flux_2_pro_model_name"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Backfill: delete duplicate usage_records keeping earliest per cost_decision_id
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            DELETE FROM usage_records
            WHERE id IN (
                SELECT id FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY cost_decision_id
                               ORDER BY created_at ASC
                           ) AS rn
                    FROM usage_records
                    WHERE cost_decision_id IS NOT NULL
                ) ranked
                WHERE rn > 1
            )
        """)
    )

    # Partial unique index: one UsageRecord per CostDecision
    op.create_index(
        "uq_usage_records_cost_decision_id",
        "usage_records",
        ["cost_decision_id"],
        unique=True,
        postgresql_where="cost_decision_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index(
        "uq_usage_records_cost_decision_id",
        table_name="usage_records",
    )
