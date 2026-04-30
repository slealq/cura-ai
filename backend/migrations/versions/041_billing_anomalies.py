"""Add billing_anomalies table and billing_failed column to pipeline_logs.

Revision ID: 041_billing_anomalies
Revises: 040_add_vision_result_cost
Create Date: 2026-02-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "041_billing_anomalies"
down_revision: Union[str, None] = "040_add_vision_result_cost"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create billing_anomalies table
    op.create_table(
        "billing_anomalies",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("anomaly_type", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("operation", sa.String(64), nullable=True),
        sa.Column("detail", sa.dialects.postgresql.JSON, nullable=True),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_billing_anomalies_type_created",
        "billing_anomalies",
        ["anomaly_type", "created_at"],
    )

    # Add billing_failed column to pipeline_logs
    op.add_column(
        "pipeline_logs",
        sa.Column("billing_failed", sa.Boolean, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pipeline_logs", "billing_failed")
    op.drop_index("ix_billing_anomalies_type_created", table_name="billing_anomalies")
    op.drop_table("billing_anomalies")
