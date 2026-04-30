"""Add gpt-5.2 and gpt-5-mini cost catalog entries.

Revision ID: 032_add_gpt5_pricing
Revises: 031_add_expand_prompt_cost
"""
from typing import Sequence, Union

from alembic import op

revision: str = "032_add_gpt5_pricing"
down_revision: Union[str, None] = "031_add_expand_prompt_cost"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# gpt-5.2: $1.75/1M input = 0.00000175, $14.00/1M output = 0.000014
# gpt-5-mini: $0.25/1M input = 0.00000025, $2.00/1M output = 0.000002

GPT52_OPERATIONS = [
    "tag",
    "describe",
    "evaluate",
    "evaluate_creative",
    "summarize",
    "summarize_eval",
    "generate_prompts",
]

GPT5_MINI_OPERATIONS = [
    "expand_prompt",
]


def upgrade() -> None:
    # gpt-5.2 entries
    for op_name in GPT52_OPERATIONS:
        op.execute(f"""
            INSERT INTO cost_catalog
                (provider, model, operation, cost_per_input_token, cost_per_output_token, cost_per_call, platform_markup, is_active)
            VALUES
                ('openai', 'gpt-5.2', '{op_name}', 0.00000175, 0.000014, 0, 2.0, true)
            ON CONFLICT (provider, model, operation) DO NOTHING
        """)

    # gpt-5-mini entries
    for op_name in GPT5_MINI_OPERATIONS:
        op.execute(f"""
            INSERT INTO cost_catalog
                (provider, model, operation, cost_per_input_token, cost_per_output_token, cost_per_call, platform_markup, is_active)
            VALUES
                ('openai', 'gpt-5-mini', '{op_name}', 0.00000025, 0.000002, 0, 2.0, true)
            ON CONFLICT (provider, model, operation) DO NOTHING
        """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM cost_catalog
        WHERE (provider = 'openai' AND model = 'gpt-5.2')
           OR (provider = 'openai' AND model = 'gpt-5-mini')
    """)
