"""Fix jobtype enum case: rename lowercase generation values to uppercase.

Migration 011 added lora_train, generate_image, batch_generate in lowercase,
but the existing convention (from create_all) uses uppercase enum names.

Revision ID: 013_fix_jobtype_enum_case
Revises: 012_add_api_keys_table
"""
from alembic import op

revision = "013_fix_jobtype_enum_case"
down_revision = "012_add_api_keys_table"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE jobtype RENAME VALUE 'lora_train' TO 'LORA_TRAIN'")
    op.execute("ALTER TYPE jobtype RENAME VALUE 'generate_image' TO 'GENERATE_IMAGE'")
    op.execute("ALTER TYPE jobtype RENAME VALUE 'batch_generate' TO 'BATCH_GENERATE'")


def downgrade() -> None:
    op.execute("ALTER TYPE jobtype RENAME VALUE 'LORA_TRAIN' TO 'lora_train'")
    op.execute("ALTER TYPE jobtype RENAME VALUE 'GENERATE_IMAGE' TO 'generate_image'")
    op.execute("ALTER TYPE jobtype RENAME VALUE 'BATCH_GENERATE' TO 'batch_generate'")
