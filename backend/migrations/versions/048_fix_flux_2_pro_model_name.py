"""Fix flux-2-pro model name in cost_catalog.

The 047 migration seeded the wrong model name (fal-ai/flux-pro/v1.1-ultra)
for flux-2-pro. This migration renames it to the correct fal-ai/flux-2-pro.

Revision ID: 048_fix_flux_2_pro_model_name
Revises: 047_add_pricing_rules
Create Date: 2026-03-03
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "048_fix_flux_2_pro_model_name"
down_revision: Union[str, None] = "047_add_pricing_rules"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE cost_catalog
            SET model = 'fal-ai/flux-2-pro', updated_at = NOW()
            WHERE provider = 'fal'
              AND model = 'fal-ai/flux-pro/v1.1-ultra'
              AND operation = 'generate'
        """)
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE cost_catalog
            SET model = 'fal-ai/flux-pro/v1.1-ultra', updated_at = NOW()
            WHERE provider = 'fal'
              AND model = 'fal-ai/flux-2-pro'
              AND operation = 'generate'
        """)
    )
