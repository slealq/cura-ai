"""Add LLM operation entries for gpt-4o-mini and gpt-5-mini.

Revision ID: 034_add_mini_model_llm_ops
Revises: 033_add_usage_record_detail
"""
from typing import Sequence, Union

from alembic import op

revision: str = "034_add_mini_model_llm_ops"
down_revision: Union[str, None] = "033_add_usage_record_detail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# These 7 LLM operations are seeded for both mini models.
# expand_prompt already exists for both from migrations 031/032.
LLM_OPERATIONS = [
    "tag",
    "describe",
    "evaluate",
    "evaluate_creative",
    "summarize",
    "summarize_eval",
    "generate_prompts",
]

# gpt-4o-mini: $0.15/1M input = 0.00000015, $0.60/1M output = 0.0000006
# gpt-5-mini:  $0.25/1M input = 0.00000025, $2.00/1M output = 0.000002
MINI_MODELS = [
    ("gpt-4o-mini", "0.00000015", "0.0000006"),
    ("gpt-5-mini", "0.00000025", "0.000002"),
]


def upgrade() -> None:
    for model, input_cost, output_cost in MINI_MODELS:
        for op_name in LLM_OPERATIONS:
            op.execute(f"""
                INSERT INTO cost_catalog
                    (provider, model, operation, cost_per_input_token, cost_per_output_token, cost_per_call, platform_markup, is_active)
                VALUES
                    ('openai', '{model}', '{op_name}', {input_cost}, {output_cost}, 0, 2.0, true)
                ON CONFLICT (provider, model, operation) DO NOTHING
            """)


def downgrade() -> None:
    ops_list = ", ".join(f"'{o}'" for o in LLM_OPERATIONS)
    for model, _, _ in MINI_MODELS:
        op.execute(f"""
            DELETE FROM cost_catalog
            WHERE provider = 'openai'
              AND model = '{model}'
              AND operation IN ({ops_list})
        """)
