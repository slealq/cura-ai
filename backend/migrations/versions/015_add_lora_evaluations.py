"""Add lora_evaluations and evaluation_pairs tables.

Revision ID: 015_lora_evaluations
Revises: 014_lora_cluster_id
"""
import sqlalchemy as sa
from alembic import op

revision = "015_lora_evaluations"
down_revision = "014_lora_cluster_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add LORA_EVALUATE to jobtype enum (uppercase matches project convention, see migration 013)
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'LORA_EVALUATE'")

    # Create lora_evaluations table
    op.create_table(
        "lora_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("lora_model_id", sa.Integer(), sa.ForeignKey("lora_models.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("config", sa.dialects.postgresql.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("avg_embedding_similarity", sa.Float(), nullable=True),
        sa.Column("avg_vision_score", sa.Float(), nullable=True),
        sa.Column("avg_clip_image_score", sa.Float(), nullable=True),
        sa.Column("avg_clip_text_score", sa.Float(), nullable=True),
        sa.Column("assessment_summary", sa.Text(), nullable=True),
        sa.Column("aggregate_results", sa.dialects.postgresql.JSON(), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_lora_evaluations_model_created", "lora_evaluations", ["lora_model_id", "created_at"])
    op.create_index("ix_lora_evaluations_status", "lora_evaluations", ["status"])

    # Create evaluation_pairs table
    op.create_table(
        "evaluation_pairs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("evaluation_id", sa.Integer(), sa.ForeignKey("lora_evaluations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("original_image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt_used", sa.Text(), nullable=True),
        sa.Column("generated_object_key", sa.String(512), nullable=True),
        sa.Column("generated_width", sa.Integer(), nullable=True),
        sa.Column("generated_height", sa.Integer(), nullable=True),
        sa.Column("generated_thumbnail_small", sa.Text(), nullable=True),
        sa.Column("generated_thumbnail_medium", sa.Text(), nullable=True),
        sa.Column("embedding_similarity", sa.Float(), nullable=True),
        sa.Column("vision_score", sa.Float(), nullable=True),
        sa.Column("vision_assessment", sa.Text(), nullable=True),
        sa.Column("clip_image_score", sa.Float(), nullable=True),
        sa.Column("clip_text_score", sa.Float(), nullable=True),
        sa.Column("pair_score", sa.Float(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics_detail", sa.dialects.postgresql.JSON(), nullable=True),
    )
    op.create_index("ix_evaluation_pairs_evaluation_id", "evaluation_pairs", ["evaluation_id"])


def downgrade() -> None:
    op.drop_table("evaluation_pairs")
    op.drop_table("lora_evaluations")
