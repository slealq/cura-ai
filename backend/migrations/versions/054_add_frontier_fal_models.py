"""Add frontier fal.ai models to the cost catalog.

Revision ID: 054_add_frontier_fal_models
Revises: 053_add_subscriptions_and_promos
Create Date: 2026-07-24
"""
import json
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "054_add_frontier_fal_models"
down_revision: Union[str, None] = "053_add_subscriptions_and_promos"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

FLUX_2_MP_RULES = json.dumps({
    "pricing_type": "megapixel",
    "first_mp_cost": 0.021,
    "extra_mp_cost": 0.021,
    "default_width": 1024,
    "default_height": 1024,
})

SEEDREAM_5_PRO_RULES = json.dumps({
    "pricing_type": "flat_with_modifiers",
    "base_cost": 0.0675,
    "resolution_multipliers": {"up_to_1536": 1.0, "over_1536_to_2048": 2.0},
    "default_resolution": "up_to_1536",
})

SEEDREAM_5_PRO_EDIT_RULES = json.dumps({
    "pricing_type": "flat_with_modifiers",
    "base_cost": 0.0675,
    "resolution_multipliers": {"up_to_1536": 1.0, "over_1536_to_2048": 2.0},
    "default_resolution": "up_to_1536",
    # Pricing engine support for edit input-count surcharges is future work.
    "surcharges": {"per_additional_input_image": 0.0045},
})


def _upsert(
    conn,
    *,
    model: str,
    operation: str,
    cost_per_call: float,
    pricing_rules: str | None = None,
) -> None:
    conn.execute(
        sa.text("""
            INSERT INTO cost_catalog (provider, model, operation, cost_per_call, platform_markup,
                pricing_rules, is_active, created_at, updated_at)
            VALUES ('fal', :model, :operation, :cost_per_call, 2.0,
                :pricing_rules, true, NOW(), NOW())
            ON CONFLICT (provider, model, operation) DO UPDATE SET
                cost_per_call = EXCLUDED.cost_per_call,
                platform_markup = EXCLUDED.platform_markup,
                pricing_rules = EXCLUDED.pricing_rules,
                is_active = EXCLUDED.is_active,
                updated_at = NOW()
        """),
        {
            "model": model,
            "operation": operation,
            "cost_per_call": cost_per_call,
            "pricing_rules": pricing_rules,
        },
    )


def upgrade() -> None:
    conn = op.get_bind()

    # Base FLUX.2 pricing is estimated from the published LoRA model-family rate.
    _upsert(
        conn,
        model="fal-ai/flux-2",
        operation="generate",
        cost_per_call=0.021,
        pricing_rules=FLUX_2_MP_RULES,
    )
    _upsert(
        conn,
        model="fal-ai/flux-2/lora",
        operation="generate",
        cost_per_call=0.021,
        pricing_rules=FLUX_2_MP_RULES,
    )
    _upsert(
        conn,
        model="fal-ai/flux-2-trainer-v2",
        operation="train",
        cost_per_call=6.40,
    )
    _upsert(
        conn,
        model="bytedance/seedream/v5/pro/text-to-image",
        operation="generate",
        cost_per_call=0.0675,
        pricing_rules=SEEDREAM_5_PRO_RULES,
    )
    _upsert(
        conn,
        model="bytedance/seedream/v5/pro/edit",
        operation="edit",
        cost_per_call=0.0675,
        pricing_rules=SEEDREAM_5_PRO_EDIT_RULES,
    )
    # Tentative estimate pending official fal.ai pricing.
    _upsert(
        conn,
        model="fal-ai/qwen-image-2/pro/edit",
        operation="edit",
        cost_per_call=0.05,
    )
    _upsert(
        conn,
        model="fal-ai/flux-2/lora/edit",
        operation="edit",
        cost_per_call=0.021,
        pricing_rules=FLUX_2_MP_RULES,
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("""
            DELETE FROM cost_catalog
            WHERE provider = 'fal'
              AND (model, operation) IN (
                  ('fal-ai/flux-2', 'generate'),
                  ('fal-ai/flux-2/lora', 'generate'),
                  ('fal-ai/flux-2-trainer-v2', 'train'),
                  ('bytedance/seedream/v5/pro/text-to-image', 'generate'),
                  ('bytedance/seedream/v5/pro/edit', 'edit'),
                  ('fal-ai/qwen-image-2/pro/edit', 'edit'),
                  ('fal-ai/flux-2/lora/edit', 'edit')
              )
        """)
    )
