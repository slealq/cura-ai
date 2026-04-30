"""Add pricing_rules JSON column to cost_catalog and seed new models.

Revision ID: 047_add_pricing_rules
Revises: 046_add_reserved_sparks
Create Date: 2026-03-03
"""
import json
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "047_add_pricing_rules"
down_revision: Union[str, None] = "046_add_reserved_sparks"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

# Pricing rules for each model
NANO_BANANA_PRO_RULES = json.dumps({
    "pricing_type": "flat_with_modifiers",
    "base_cost": 0.15,
    "resolution_multipliers": {"1K": 1.0, "4K": 2.0},
    "default_resolution": "1K",
    "surcharges": {"web_search": 0.015},
})

NANO_BANANA_2_RULES = json.dumps({
    "pricing_type": "flat_with_modifiers",
    "base_cost": 0.08,
    "resolution_multipliers": {"0.5K": 0.75, "1K": 1.0, "2K": 1.5, "4K": 2.0},
    "default_resolution": "1K",
    "surcharges": {"web_search": 0.015},
})

FLUX_2_PRO_RULES = json.dumps({
    "pricing_type": "megapixel",
    "first_mp_cost": 0.03,
    "extra_mp_cost": 0.015,
    "default_width": 1024,
    "default_height": 1024,
})


def upgrade() -> None:
    # 1. Add pricing_rules JSON column
    op.add_column(
        "cost_catalog",
        sa.Column("pricing_rules", sa.JSON(), nullable=True),
    )

    conn = op.get_bind()

    # 2. Fix nano-banana-pro generate (was $0.039, actual $0.15)
    conn.execute(
        sa.text("""
            UPDATE cost_catalog
            SET cost_per_call = 0.15,
                pricing_rules = :rules
            WHERE provider = 'fal'
              AND model = 'fal-ai/nano-banana-pro'
              AND operation = 'generate'
        """),
        {"rules": NANO_BANANA_PRO_RULES},
    )

    # 3. Fix nano-banana-pro edit (same pricing issue)
    conn.execute(
        sa.text("""
            UPDATE cost_catalog
            SET cost_per_call = 0.15,
                pricing_rules = :rules
            WHERE provider = 'fal'
              AND model = 'fal-ai/nano-banana-pro/edit'
              AND operation = 'edit'
        """),
        {"rules": NANO_BANANA_PRO_RULES},
    )

    # 4. Seed nano-banana-2
    conn.execute(
        sa.text("""
            INSERT INTO cost_catalog (provider, model, operation, cost_per_call, platform_markup,
                pricing_rules, is_active, created_at, updated_at)
            VALUES ('fal', 'fal-ai/nano-banana-2', 'generate', 0.08, 2.0,
                :rules, true, NOW(), NOW())
            ON CONFLICT (provider, model, operation) DO UPDATE SET
                cost_per_call = EXCLUDED.cost_per_call,
                pricing_rules = EXCLUDED.pricing_rules,
                updated_at = NOW()
        """),
        {"rules": NANO_BANANA_2_RULES},
    )

    # 5. Seed flux-2-pro
    conn.execute(
        sa.text("""
            INSERT INTO cost_catalog (provider, model, operation, cost_per_call, platform_markup,
                pricing_rules, is_active, created_at, updated_at)
            VALUES ('fal', 'fal-ai/flux-2-pro', 'generate', 0.03, 2.0,
                :rules, true, NOW(), NOW())
            ON CONFLICT (provider, model, operation) DO UPDATE SET
                cost_per_call = EXCLUDED.cost_per_call,
                pricing_rules = EXCLUDED.pricing_rules,
                updated_at = NOW()
        """),
        {"rules": FLUX_2_PRO_RULES},
    )


def downgrade() -> None:
    conn = op.get_bind()

    # Revert nano-banana-pro generate price
    conn.execute(sa.text("""
        UPDATE cost_catalog
        SET cost_per_call = 0.039, pricing_rules = NULL
        WHERE provider = 'fal'
          AND model = 'fal-ai/nano-banana-pro'
          AND operation = 'generate'
    """))

    # Revert nano-banana-pro edit price
    conn.execute(sa.text("""
        UPDATE cost_catalog
        SET cost_per_call = 0.039, pricing_rules = NULL
        WHERE provider = 'fal'
          AND model = 'fal-ai/nano-banana-pro/edit'
          AND operation = 'edit'
    """))

    # Remove seeded entries
    conn.execute(sa.text("""
        DELETE FROM cost_catalog
        WHERE provider = 'fal'
          AND model IN ('fal-ai/nano-banana-2', 'fal-ai/flux-2-pro')
    """))

    op.drop_column("cost_catalog", "pricing_rules")
