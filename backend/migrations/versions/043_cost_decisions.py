"""Create cost_decisions table and extend usage_records.

Revision ID: 043_cost_decisions
Revises: 042_add_trace_id_columns
Create Date: 2026-02-26
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "043_cost_decisions"
down_revision: Union[str, None] = "042_add_trace_id_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cost_decisions",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column("trace_id", sa.String(256), nullable=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("catalog_entry_id", sa.Integer, sa.ForeignKey("cost_catalog.id", ondelete="SET NULL"), nullable=True),
        sa.Column("catalog_match_tier", sa.String(16), nullable=True),
        sa.Column("estimated_input_tokens", sa.Integer, nullable=True),
        sa.Column("estimated_output_tokens", sa.Integer, nullable=True),
        sa.Column("estimated_sparks", sa.Integer, nullable=True),
        sa.Column("cost_per_input_token", sa.Numeric(20, 12), nullable=True),
        sa.Column("cost_per_output_token", sa.Numeric(20, 12), nullable=True),
        sa.Column("cost_per_call", sa.Numeric(12, 6), nullable=True),
        sa.Column("platform_markup", sa.Numeric(5, 4), nullable=True),
        sa.Column("billing_model", sa.String(32), nullable=True),
        sa.Column("image_id", sa.Integer, nullable=True),
        sa.Column("resource_id", sa.Integer, nullable=True),
        sa.Column("request_snapshot", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("response_snapshot", sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("idempotency_key", sa.String(256), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_cost_decisions_trace_id", "cost_decisions", ["trace_id"])
    op.create_index("ix_cost_decisions_user_created", "cost_decisions", ["user_id", "created_at"])
    op.create_index("ix_cost_decisions_job_id", "cost_decisions", ["job_id"])
    op.create_index("ix_cost_decisions_status", "cost_decisions", ["status"])
    op.create_index("ix_cost_decisions_image_id", "cost_decisions", ["image_id"])

    # Extend usage_records
    op.add_column(
        "usage_records",
        sa.Column("cost_decision_id", sa.Integer, sa.ForeignKey("cost_decisions.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_usage_records_cost_decision_id", "usage_records", ["cost_decision_id"])

    op.add_column(
        "usage_records",
        sa.Column("provider_request_id", sa.String(256), nullable=True),
    )

    op.add_column(
        "usage_records",
        sa.Column("delta_sparks", sa.Integer, nullable=True),
    )

    op.add_column(
        "usage_records",
        sa.Column("delta_reason", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("usage_records", "delta_reason")
    op.drop_column("usage_records", "delta_sparks")
    op.drop_column("usage_records", "provider_request_id")
    op.drop_index("ix_usage_records_cost_decision_id", table_name="usage_records")
    op.drop_column("usage_records", "cost_decision_id")

    op.drop_index("ix_cost_decisions_image_id", table_name="cost_decisions")
    op.drop_index("ix_cost_decisions_status", table_name="cost_decisions")
    op.drop_index("ix_cost_decisions_job_id", table_name="cost_decisions")
    op.drop_index("ix_cost_decisions_user_created", table_name="cost_decisions")
    op.drop_index("ix_cost_decisions_trace_id", table_name="cost_decisions")
    op.drop_table("cost_decisions")
