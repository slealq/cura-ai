"""Fix nano-banana-pro pricing and add charged_cost to jobs.

Revision ID: 030_nano_pricing_job_cost
Revises: 029_add_usage_billing_tables
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "030_nano_pricing_job_cost"
down_revision: Union[str, None] = "029_add_usage_billing_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix nano-banana-pro pricing (was 0.15, should be 0.039)
    op.execute(
        sa.text(
            "UPDATE cost_catalog SET cost_per_call = 0.039, updated_at = NOW() "
            "WHERE model = 'fal-ai/nano-banana-pro' AND operation = 'generate'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE cost_catalog SET cost_per_call = 0.039, updated_at = NOW() "
            "WHERE model = 'fal-ai/nano-banana-pro/edit' AND operation = 'edit'"
        )
    )

    # Add charged_cost column to jobs table
    op.add_column("jobs", sa.Column("charged_cost", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "charged_cost")

    # Revert nano-banana-pro pricing
    op.execute(
        sa.text(
            "UPDATE cost_catalog SET cost_per_call = 0.15, updated_at = NOW() "
            "WHERE model = 'fal-ai/nano-banana-pro' AND operation = 'generate'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE cost_catalog SET cost_per_call = 0.15, updated_at = NOW() "
            "WHERE model = 'fal-ai/nano-banana-pro/edit' AND operation = 'edit'"
        )
    )
