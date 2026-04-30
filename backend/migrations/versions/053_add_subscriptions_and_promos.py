"""Add subscription plans, user subscriptions, promo codes, and promo redemptions.

Revision ID: 053_add_subscriptions_and_promos
Revises: 052_add_payment_tables
Create Date: 2026-03-04
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "053_add_subscriptions_and_promos"
down_revision: Union[str, None] = "052_add_payment_tables"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # --- subscriptionstatus enum ---
    subscriptionstatus = sa.Enum(
        "active", "cancelled", "expired", "paused", "past_due",
        name="subscriptionstatus",
    )

    # --- subscription_plans ---
    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sparks_per_month", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_variant_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- user_subscriptions ---
    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "plan_id", sa.Integer(),
            sa.ForeignKey("subscription_plans.id"), nullable=False,
        ),
        sa.Column(
            "status", subscriptionstatus, nullable=False, server_default="active",
        ),
        sa.Column("provider", sa.String(64), nullable=False, server_default="lemon_squeezy"),
        sa.Column("provider_subscription_id", sa.String(256), nullable=True, unique=True),
        sa.Column("current_period_start", sa.DateTime(), nullable=True),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("sparks_granted_this_period", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_user_subscriptions_user_status",
        "user_subscriptions", ["user_id", "status"],
    )

    # --- promo_codes ---
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("sparks_amount", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("uses_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- promo_redemptions ---
    op.create_table(
        "promo_redemptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "promo_code_id", sa.Integer(),
            sa.ForeignKey("promo_codes.id"), nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("sparks_granted", sa.Integer(), nullable=False),
        sa.Column(
            "balance_txn_id", sa.Integer(),
            sa.ForeignKey("balance_transactions.id"), nullable=True,
        ),
        sa.Column("redeemed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("promo_code_id", "user_id", name="uq_promo_redemption_user"),
    )

    # --- Seed default subscription plans ---
    plans_table = sa.table(
        "subscription_plans",
        sa.column("name", sa.String),
        sa.column("sparks_per_month", sa.Integer),
        sa.column("price_cents", sa.Integer),
        sa.column("currency", sa.String),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(plans_table, [
        {"name": "Hobby", "sparks_per_month": 15000, "price_cents": 1500, "currency": "USD", "sort_order": 1},
        {"name": "Pro", "sparks_per_month": 45000, "price_cents": 4000, "currency": "USD", "sort_order": 2},
        {"name": "Studio", "sparks_per_month": 100000, "price_cents": 8000, "currency": "USD", "sort_order": 3},
    ])


def downgrade() -> None:
    op.drop_table("promo_redemptions")
    op.drop_table("promo_codes")
    op.drop_table("user_subscriptions")
    op.drop_table("subscription_plans")
    sa.Enum(name="subscriptionstatus").drop(op.get_bind(), checkfirst=True)
