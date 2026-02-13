"""Add lora_models and generated_images tables, extend jobtype enum.

Revision ID: 011_add_lora_and_generation
Revises: 010_add_folders
"""
import sqlalchemy as sa
from alembic import op

revision = "011_add_lora_and_generation"
down_revision = "010_add_folders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add new values to jobtype enum
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'lora_train'")
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'generate_image'")
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'batch_generate'")

    # Use sa.String for status columns — the actual enum type is managed by the ORM models.
    # This avoids conflicts between Alembic and SQLAlchemy both trying to create enum types.

    op.create_table(
        "lora_models",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("trigger_word", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("folder_id", sa.Integer(), sa.ForeignKey("folders.id", ondelete="SET NULL"), nullable=True),
        sa.Column("base_model", sa.String(128), nullable=False, server_default="flux-dev"),
        sa.Column("training_provider", sa.String(64), nullable=False),
        sa.Column("training_config", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("lora_url", sa.Text(), nullable=True),
        sa.Column("lora_local_path", sa.Text(), nullable=True),
        sa.Column("training_images_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_metadata", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("training_started_at", sa.DateTime(), nullable=True),
        sa.Column("training_completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_lora_models_folder_id", "lora_models", ["folder_id"])
    op.create_index("ix_lora_models_job_id", "lora_models", ["job_id"])
    op.create_index("ix_lora_models_status", "lora_models", ["status"])

    # Create generated_images table
    op.create_table(
        "generated_images",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("negative_prompt", sa.Text(), nullable=True),
        sa.Column("base_model", sa.String(128), nullable=False),
        sa.Column("generation_provider", sa.String(64), nullable=False),
        sa.Column("lora_model_id", sa.Integer(), sa.ForeignKey("lora_models.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lora_scale", sa.Float(), nullable=True),
        sa.Column("generation_params", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("object_key", sa.String(512), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(64), nullable=True),
        sa.Column("thumbnail_uri_small", sa.Text(), nullable=True),
        sa.Column("thumbnail_uri_medium", sa.Text(), nullable=True),
        sa.Column("provider_metadata", sa.JSON(), nullable=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_index("ix_generated_images_lora_model_id", "generated_images", ["lora_model_id"])
    op.create_index("ix_generated_images_job_id", "generated_images", ["job_id"])
    op.create_index("ix_generated_images_status", "generated_images", ["status"])
    op.create_index("ix_generated_images_created_at", "generated_images", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_generated_images_created_at", table_name="generated_images")
    op.drop_index("ix_generated_images_status", table_name="generated_images")
    op.drop_index("ix_generated_images_job_id", table_name="generated_images")
    op.drop_index("ix_generated_images_lora_model_id", table_name="generated_images")
    op.drop_table("generated_images")

    op.drop_index("ix_lora_models_status", table_name="lora_models")
    op.drop_index("ix_lora_models_job_id", table_name="lora_models")
    op.drop_index("ix_lora_models_folder_id", table_name="lora_models")
    op.drop_table("lora_models")

    op.execute("DROP TYPE IF EXISTS generationstatus")
    op.execute("DROP TYPE IF EXISTS loramodelstatus")
