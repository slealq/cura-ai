"""Add payment tables for spark pack purchases.

Creates spark_packs, payment_transactions, and payment_webhook_events tables.
Seeds 4 default spark packs (Starter, Creator, Pro, Studio).

Revision ID: 052_add_payment_tables
Revises: 051_fractional_sparks
Create Date: 2026-03-04
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

# revision identifiers
revision: str = "052_add_payment_tables"
down_revision: Union[str, None] = "051_fractional_sparks"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # --- spark_packs ---
    op.create_table(
        "spark_packs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sparks_amount", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("bonus_sparks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("is_featured", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_variant_id", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # --- payment_webhook_events (must come before payment_transactions due to FK) ---
    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("provider_event_id", sa.String(256), nullable=False, unique=True),
        sa.Column("payload", JSON(), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_payment_webhook_events_provider_type",
        "payment_webhook_events",
        ["provider", "event_type"],
    )

    # --- payment_transactions ---
    payment_status = sa.Enum(
        "pending", "completed", "failed", "expired", "refunded", "disputed",
        name="paymentstatus",
    )
    op.create_table(
        "payment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("purchase_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("provider_payment_id", sa.String(256), nullable=True, unique=True),
        sa.Column("provider_session_id", sa.String(256), nullable=True),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
        sa.Column("pack_id", sa.Integer(), sa.ForeignKey("spark_packs.id"), nullable=False),
        sa.Column("status", payment_status, nullable=False, server_default="pending"),
        sa.Column("refunded_amount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("balance_txn_id", sa.Integer(), sa.ForeignKey("balance_transactions.id"), nullable=True),
        sa.Column("webhook_event_id", sa.Integer(), sa.ForeignKey("payment_webhook_events.id"), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_payment_transactions_user_created",
        "payment_transactions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_payment_transactions_status",
        "payment_transactions",
        ["status"],
    )

    # --- Seed default spark packs ---
    spark_packs = sa.table(
        "spark_packs",
        sa.column("name", sa.String),
        sa.column("sparks_amount", sa.Integer),
        sa.column("price_cents", sa.Integer),
        sa.column("bonus_sparks", sa.Integer),
        sa.column("currency", sa.String),
        sa.column("is_featured", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(spark_packs, [
        {
            "name": "Starter",
            "sparks_amount": 5000,
            "price_cents": 1000,
            "bonus_sparks": 2000,
            "currency": "USD",
            "is_featured": False,
            "sort_order": 1,
        },
        {
            "name": "Creator",
            "sparks_amount": 15000,
            "price_cents": 2500,
            "bonus_sparks": 7000,
            "currency": "USD",
            "is_featured": True,
            "sort_order": 2,
        },
        {
            "name": "Pro",
            "sparks_amount": 35000,
            "price_cents": 5000,
            "bonus_sparks": 13000,
            "currency": "USD",
            "is_featured": False,
            "sort_order": 3,
        },
        {
            "name": "Studio",
            "sparks_amount": 70000,
            "price_cents": 10000,
            "bonus_sparks": 35000,
            "currency": "USD",
            "is_featured": False,
            "sort_order": 4,
        },
    ])


def downgrade() -> None:
    op.drop_table("payment_transactions")
    op.execute("DROP TYPE IF EXISTS paymentstatus")
    op.drop_table("payment_webhook_events")
    op.drop_table("spark_packs")
