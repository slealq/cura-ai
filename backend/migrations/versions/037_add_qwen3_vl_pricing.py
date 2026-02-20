"""Add cost catalog entries for Qwen3 VL 235B via OpenRouter (fal provider).

Pricing from OpenRouter (2025): $0.20/M input, $0.88/M output.

Revision ID: 037_add_qwen3_vl_pricing
Revises: 036_drop_sonnet4_catalog
"""
from typing import Sequence, Union

from alembic import op

revision: str = "037_add_qwen3_vl_pricing"
down_revision: Union[str, None] = "036_drop_sonnet4_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODEL = "qwen/qwen3-vl-235b-a22b-instruct"
_PROVIDER = "fal"
_INPUT = "0.0000002"    # $0.20 per 1M tokens
_OUTPUT = "0.00000088"  # $0.88 per 1M tokens


def upgrade() -> None:
    for operation in ("tag", "describe", "evaluate", "evaluate_creative",
                      "summarize_eval", "generate_prompts"):
        op.execute(f"""
            INSERT INTO cost_catalog
                (provider, model, operation,
                 cost_per_input_token, cost_per_output_token,
                 cost_per_call, platform_markup, is_active)
            VALUES
                ('{_PROVIDER}', '{_MODEL}', '{operation}',
                 {_INPUT}, {_OUTPUT},
                 0, 2.0, true)
            ON CONFLICT (provider, model, operation) DO NOTHING
        """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM cost_catalog
        WHERE provider = '{_PROVIDER}' AND model = '{_MODEL}'
    """)
