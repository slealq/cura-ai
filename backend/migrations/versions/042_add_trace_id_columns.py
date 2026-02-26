"""Add trace_id columns to pipeline_logs, usage_records, and balance_transactions.

Revision ID: 042_add_trace_id_columns
Revises: 041_billing_anomalies
Create Date: 2026-02-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "042_add_trace_id_columns"
down_revision: Union[str, None] = "041_billing_anomalies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_logs",
        sa.Column("trace_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_pipeline_logs_trace_id", "pipeline_logs", ["trace_id"])

    op.add_column(
        "usage_records",
        sa.Column("trace_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_usage_records_trace_id", "usage_records", ["trace_id"])

    op.add_column(
        "balance_transactions",
        sa.Column("trace_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_balance_transactions_trace_id", "balance_transactions", ["trace_id"])


def downgrade() -> None:
    op.drop_index("ix_balance_transactions_trace_id", table_name="balance_transactions")
    op.drop_column("balance_transactions", "trace_id")

    op.drop_index("ix_usage_records_trace_id", table_name="usage_records")
    op.drop_column("usage_records", "trace_id")

    op.drop_index("ix_pipeline_logs_trace_id", table_name="pipeline_logs")
    op.drop_column("pipeline_logs", "trace_id")
