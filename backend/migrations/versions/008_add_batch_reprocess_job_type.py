"""Add batch_reprocess to JobType enum.

Revision ID: 008_add_batch_reprocess_job_type
Revises: 007_convert_prompts_to_guidance
"""
from alembic import op

revision = "008_add_batch_reprocess_job_type"
down_revision = "007_convert_prompts_to_guidance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'BATCH_REPROCESS'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; this is a no-op.
    pass
