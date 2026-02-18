"""Add usage and billing tables: cost_catalog, usage_records, user_balance, balance_transactions.

Revision ID: 029_add_usage_billing_tables
Revises: 028_add_prompt_timing
"""
from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "029_add_usage_billing_tables"
down_revision: Union[str, None] = "028_add_prompt_timing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Enum for transaction types — created via raw SQL to use IF NOT EXISTS
TRANSACTION_TYPE_ENUM_NAME = "transactiontype"


def upgrade() -> None:
    # --- cost_catalog ---
    op.create_table(
        "cost_catalog",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("cost_per_input_token", sa.Numeric(20, 12), nullable=True, server_default="0"),
        sa.Column("cost_per_output_token", sa.Numeric(20, 12), nullable=True, server_default="0"),
        sa.Column("cost_per_call", sa.Numeric(12, 6), nullable=True, server_default="0"),
        sa.Column("platform_markup", sa.Numeric(5, 4), nullable=False, server_default="2.0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "model", "operation", name="uq_cost_catalog_provider_model_op"),
    )
    op.create_index("ix_cost_catalog_id", "cost_catalog", ["id"])

    # --- usage_records ---
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("pipeline_log_id", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("raw_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("charged_cost", sa.Numeric(12, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_records_id", "usage_records", ["id"])
    op.create_index("ix_usage_records_user_created", "usage_records", ["user_id", "created_at"])
    op.create_index("ix_usage_records_user_operation", "usage_records", ["user_id", "operation"])

    # --- user_balance ---
    op.create_table(
        "user_balance",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("balance", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(16), nullable=False, server_default="credits"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_balance_user_id"),
    )
    op.create_index("ix_user_balance_id", "user_balance", ["id"])

    # --- balance_transactions ---
    op.execute(sa.text(
        "DO $$ BEGIN "
        "CREATE TYPE transactiontype AS ENUM ('credit', 'debit', 'adjustment'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    ))
    op.create_table(
        "balance_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 4), nullable=False),
        sa.Column("transaction_type", postgresql.ENUM("credit", "debit", "adjustment", name="transactiontype", create_type=False), nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_balance_transactions_id", "balance_transactions", ["id"])
    op.create_index("ix_balance_transactions_user_created", "balance_transactions", ["user_id", "created_at"])

    # --- Backfill user_balance for all existing users ---
    conn = op.get_bind()
    users = conn.execute(sa.text("SELECT id, email FROM users")).fetchall()
    for user in users:
        # Give admin (stuart.leal23@gmail.com) 10000 credits ($100), others 0
        balance = Decimal("10000") if user.email == "stuart.leal23@gmail.com" else Decimal("0")
        conn.execute(
            sa.text(
                "INSERT INTO user_balance (user_id, balance, currency, updated_at) "
                "VALUES (:user_id, :balance, 'credits', NOW())"
            ),
            {"user_id": user.id, "balance": balance},
        )
        if balance > 0:
            conn.execute(
                sa.text(
                    "INSERT INTO balance_transactions (user_id, amount, transaction_type, description, created_at) "
                    "VALUES (:user_id, :amount, 'credit', 'Initial admin credit', NOW())"
                ),
                {"user_id": user.id, "amount": balance},
            )

    # --- Seed cost catalog ---
    # Format: (provider, model, operation, cost_per_input_token, cost_per_output_token, cost_per_call, markup)
    catalog_entries = [
        # OpenAI GPT-4o operations (per-token pricing)
        ("openai", "gpt-4o", "tag", "0.0000025", "0.00001", "0", "2.0"),
        ("openai", "gpt-4o", "describe", "0.0000025", "0.00001", "0", "2.0"),
        ("openai", "gpt-4o", "evaluate", "0.0000025", "0.00001", "0", "2.0"),
        ("openai", "gpt-4o", "evaluate_creative", "0.0000025", "0.00001", "0", "2.0"),
        ("openai", "gpt-4o", "summarize", "0.0000025", "0.00001", "0", "2.0"),
        ("openai", "gpt-4o", "summarize_eval", "0.0000025", "0.00001", "0", "2.0"),
        ("openai", "gpt-4o", "generate_prompts", "0.0000025", "0.00001", "0", "2.0"),
        # OpenAI embeddings
        ("openai", "text-embedding-3-small", "embed", "0.00000002", "0", "0", "2.0"),
        # Anthropic operations (per-token pricing)
        ("anthropic", "claude-sonnet-4-20250514", "tag", "0.000003", "0.000015", "0", "2.0"),
        ("anthropic", "claude-sonnet-4-20250514", "describe", "0.000003", "0.000015", "0", "2.0"),
        ("anthropic", "claude-sonnet-4-20250514", "evaluate", "0.000003", "0.000015", "0", "2.0"),
        ("anthropic", "claude-sonnet-4-20250514", "summarize", "0.000003", "0.000015", "0", "2.0"),
        # fal.ai generation (per-call, varies by model — ~1MP default resolution)
        ("fal", "fal-ai/flux-lora", "generate", "0", "0", "0.035", "2.0"),
        ("fal", "fal-ai/flux/dev", "generate", "0", "0", "0.025", "2.0"),
        ("fal", "fal-ai/qwen-image-2512/lora", "generate", "0", "0", "0.035", "2.0"),
        ("fal", "fal-ai/qwen-image-2512", "generate", "0", "0", "0.02", "2.0"),
        ("fal", "fal-ai/nano-banana-pro", "generate", "0", "0", "0.15", "2.0"),
        # fal.ai training (per-call — cost represents ~1000 steps default)
        ("fal", "fal-ai/flux-lora-fast-training", "train", "0", "0", "2.00", "2.0"),
        ("fal", "fal-ai/qwen-image-2512-trainer-v2", "train", "0", "0", "1.90", "2.0"),
        # fal.ai edit (per-call, varies by model)
        ("fal", "fal-ai/qwen-image-max/edit", "edit", "0", "0", "0.075", "2.0"),
        ("fal", "fal-ai/kling-image/o3/image-to-image", "edit", "0", "0", "0.028", "2.0"),
        ("fal", "fal-ai/wan-25-preview/image-to-image", "edit", "0", "0", "0.05", "2.0"),
        ("fal", "xai/grok-imagine-image/edit", "edit", "0", "0", "0.022", "2.0"),
        ("fal", "half-moon-ai/ai-face-swap/faceswapimage", "edit", "0", "0", "0.009", "2.0"),
        ("fal", "fal-ai/nano-banana-pro/edit", "edit", "0", "0", "0.15", "2.0"),
        # fal.ai OpenRouter vision (per-token: $0.20/1M input, $0.50/1M output)
        ("fal", "x-ai/grok-4-fast", "tag", "0.0000002", "0.0000005", "0", "2.0"),
        ("fal", "x-ai/grok-4-fast", "describe", "0.0000002", "0.0000005", "0", "2.0"),
        ("fal", "x-ai/grok-4-fast", "evaluate", "0.0000002", "0.0000005", "0", "2.0"),
        ("fal", "x-ai/grok-4-fast", "evaluate_creative", "0.0000002", "0.0000005", "0", "2.0"),
        ("fal", "x-ai/grok-4-fast", "summarize_eval", "0.0000002", "0.0000005", "0", "2.0"),
        ("fal", "x-ai/grok-4-fast", "generate_prompts", "0.0000002", "0.0000005", "0", "2.0"),
    ]
    for provider, model, operation, cpit, cpot, cpc, markup in catalog_entries:
        conn.execute(
            sa.text(
                "INSERT INTO cost_catalog (provider, model, operation, cost_per_input_token, "
                "cost_per_output_token, cost_per_call, platform_markup, is_active, created_at, updated_at) "
                "VALUES (:provider, :model, :operation, :cpit, :cpot, :cpc, :markup, true, NOW(), NOW())"
            ),
            {
                "provider": provider,
                "model": model,
                "operation": operation,
                "cpit": cpit,
                "cpot": cpot,
                "cpc": cpc,
                "markup": markup,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_balance_transactions_user_created", table_name="balance_transactions")
    op.drop_index("ix_balance_transactions_id", table_name="balance_transactions")
    op.drop_table("balance_transactions")
    op.execute(sa.text("DROP TYPE IF EXISTS transactiontype"))

    op.drop_index("ix_user_balance_id", table_name="user_balance")
    op.drop_table("user_balance")

    op.drop_index("ix_usage_records_user_operation", table_name="usage_records")
    op.drop_index("ix_usage_records_user_created", table_name="usage_records")
    op.drop_index("ix_usage_records_id", table_name="usage_records")
    op.drop_table("usage_records")

    op.drop_index("ix_cost_catalog_id", table_name="cost_catalog")
    op.drop_table("cost_catalog")
