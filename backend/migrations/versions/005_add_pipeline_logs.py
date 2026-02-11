"""Add pipeline_logs table.

Revision ID: 005_add_pipeline_logs
Revises: 004_add_job_image_id
"""
from alembic import op
import sqlalchemy as sa

revision = "005_add_pipeline_logs"
down_revision = "004_add_job_image_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "level",
            sa.Enum("debug", "info", "warning", "error", name="loglevel"),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum("api_call", "task", "pipeline", "system", name="logcategory"),
            nullable=False,
        ),
        sa.Column("image_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.String(128), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("operation", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_pipeline_logs_id", "pipeline_logs", ["id"])
    op.create_index("ix_pipeline_logs_image_id", "pipeline_logs", ["image_id"])
    op.create_index("ix_pipeline_logs_job_id", "pipeline_logs", ["job_id"])
    op.create_index("ix_pipeline_logs_created_at", "pipeline_logs", ["created_at"])
    op.create_index(
        "ix_pipeline_logs_category_created",
        "pipeline_logs",
        ["category", "created_at"],
    )
    op.create_index(
        "ix_pipeline_logs_level_created",
        "pipeline_logs",
        ["level", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("pipeline_logs")
    op.execute("DROP TYPE IF EXISTS loglevel")
    op.execute("DROP TYPE IF EXISTS logcategory")
