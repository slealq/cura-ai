"""Add expand_prompt cost catalog entry.

Revision ID: 031_add_expand_prompt_cost
Revises: 030_nano_pricing_job_cost
"""
from typing import Sequence, Union

from alembic import op

revision: str = "031_add_expand_prompt_cost"
down_revision: Union[str, None] = "030_nano_pricing_job_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO cost_catalog (provider, model, operation, cost_per_input_token, cost_per_output_token, platform_markup, is_active)
        VALUES ('openai', 'gpt-4o-mini', 'expand_prompt', 0.00000015, 0.0000006, 2.0, true)
        ON CONFLICT (provider, model, operation) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM cost_catalog
        WHERE provider = 'openai' AND model = 'gpt-4o-mini' AND operation = 'expand_prompt'
    """)
