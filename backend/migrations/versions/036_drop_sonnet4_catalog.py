"""Remove legacy claude-sonnet-4-20250514 cost catalog entries.

Model replaced by claude-sonnet-4-6 in curated Anthropic vision list.

Revision ID: 036_drop_sonnet4_catalog
Revises: 035_anthropic_model_pricing
"""
from typing import Sequence, Union

from alembic import op

revision: str = "036_drop_sonnet4_catalog"
down_revision: Union[str, None] = "035_anthropic_model_pricing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM cost_catalog
        WHERE provider = 'anthropic'
          AND model = 'claude-sonnet-4-20250514'
    """)


def downgrade() -> None:
    for operation in ("tag", "describe", "evaluate", "summarize"):
        op.execute(f"""
            INSERT INTO cost_catalog
                (provider, model, operation, cost_per_input_token, cost_per_output_token, cost_per_call, platform_markup, is_active)
            VALUES
                ('anthropic', 'claude-sonnet-4-20250514', '{operation}', 0.000003, 0.000015, 0, 2.0, true)
            ON CONFLICT (provider, model, operation) DO NOTHING
        """)
