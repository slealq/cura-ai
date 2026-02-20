"""Add cost catalog entries for Gemini 2.5 Flash via OpenRouter (fal provider).

Pricing from OpenRouter (2025): $0.30/M input, $2.50/M output.

Revision ID: 038_add_gemini_flash_pricing
Revises: 037_add_qwen3_vl_pricing
"""
from typing import Sequence, Union

from alembic import op

revision: str = "038_add_gemini_flash_pricing"
down_revision: Union[str, None] = "037_add_qwen3_vl_pricing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MODEL = "google/gemini-2.5-flash"
_PROVIDER = "fal"
_INPUT = "0.0000003"    # $0.30 per 1M tokens
_OUTPUT = "0.0000025"   # $2.50 per 1M tokens


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
