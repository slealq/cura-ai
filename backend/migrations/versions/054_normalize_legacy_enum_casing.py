"""Normalize legacy uppercase enum values.

Revision ID: 054_normalize_legacy_enum_casing
Revises: 053_add_subscriptions_and_promos
Create Date: 2026-07-16
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "054_normalize_legacy_enum_casing"
down_revision: Union[str, None] = "053_add_subscriptions_and_promos"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE clusters
            SET method = LOWER(method::text)::clusteringmethod
            WHERE method::text != LOWER(method::text)
            """
        )
    )
    conn.execute(
        sa.text(
            "UPDATE lora_models SET status = LOWER(status) WHERE status != LOWER(status)"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE generated_images SET status = LOWER(status) WHERE status != LOWER(status)"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE lora_evaluations SET status = LOWER(status) WHERE status != LOWER(status)"
        )
    )


def downgrade() -> None:
    # Casing normalization fixes invalid legacy data and is not meaningfully reversible.
    pass
