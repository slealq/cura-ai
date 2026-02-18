"""Align Anthropic cost catalog with curated vision model list.

Add entries for claude-3-haiku-20240307, claude-haiku-4-5-20251001,
claude-sonnet-4-6, and claude-opus-4-6 across all LLM operations.
Existing claude-sonnet-4-20250514 entries kept for historical records.

Revision ID: 035_anthropic_model_pricing
Revises: 034_add_mini_model_llm_ops
"""
from typing import Sequence, Union

from alembic import op

revision: str = "035_anthropic_model_pricing"
down_revision: Union[str, None] = "034_add_mini_model_llm_ops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LLM_OPERATIONS = [
    "tag",
    "describe",
    "evaluate",
    "evaluate_creative",
    "summarize",
    "summarize_eval",
    "generate_prompts",
]

# Per-token pricing from https://platform.claude.com/docs/en/about-claude/pricing
# Haiku 3:   $0.25/MTok input = 0.00000025,  $1.25/MTok output = 0.00000125
# Haiku 4.5: $1.00/MTok input = 0.000001,     $5.00/MTok output = 0.000005
# Sonnet 4.6: $3.00/MTok input = 0.000003,    $15.00/MTok output = 0.000015
# Opus 4.6:  $5.00/MTok input = 0.000005,     $25.00/MTok output = 0.000025
ANTHROPIC_MODELS = [
    ("claude-3-haiku-20240307", "0.00000025", "0.00000125"),
    ("claude-haiku-4-5-20251001", "0.000001", "0.000005"),
    ("claude-sonnet-4-6", "0.000003", "0.000015"),
    ("claude-opus-4-6", "0.000005", "0.000025"),
]


def upgrade() -> None:
    for model, input_cost, output_cost in ANTHROPIC_MODELS:
        for op_name in LLM_OPERATIONS:
            op.execute(f"""
                INSERT INTO cost_catalog
                    (provider, model, operation, cost_per_input_token, cost_per_output_token, cost_per_call, platform_markup, is_active)
                VALUES
                    ('anthropic', '{model}', '{op_name}', {input_cost}, {output_cost}, 0, 2.0, true)
                ON CONFLICT (provider, model, operation) DO NOTHING
            """)


def downgrade() -> None:
    models_list = ", ".join(f"'{m}'" for m, _, _ in ANTHROPIC_MODELS)
    op.execute(f"""
        DELETE FROM cost_catalog
        WHERE provider = 'anthropic'
          AND model IN ({models_list})
    """)
