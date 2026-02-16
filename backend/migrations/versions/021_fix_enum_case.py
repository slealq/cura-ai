"""Fix enum case: rename uppercase enum values to lowercase.

The Azure DB was created via create_all() which uses enum member NAMES
(uppercase) by default, while the model code with values_callable expects
lowercase VALUES. This migration renames affected enum values to lowercase.

Only fixes enums where the model uses values_callable (sends lowercase):
  imagestatus, imagesource, jobtype, jobstatus

Skips enums that already match or aren't used as enum columns:
  clusteringmethod (model sends uppercase names, matches DB)
  loglevel, logcategory (already lowercase in DB)
  userrole, apikeystatus, apiprovider (stored as varchar, not enum)

Revision ID: 021_fix_enum_case
Revises: 020_example_prompts
"""
from typing import Sequence, Union

from alembic import op

revision: str = "021_fix_enum_case"
down_revision: Union[str, None] = "020_example_prompts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Map of enum type -> list of (old_uppercase, new_lowercase) pairs
ENUM_RENAMES = {
    "imagestatus": [
        ("PENDING", "pending"),
        ("INGESTED", "ingested"),
        ("NORMALIZED", "normalized"),
        ("TAGGED", "tagged"),
        ("DESCRIBED", "described"),
        ("EMBEDDED", "embedded"),
        ("CLUSTERED", "clustered"),
        ("FAILED", "failed"),
    ],
    "imagesource": [
        ("UPLOAD", "upload"),
        ("FOLDER_WATCHER", "folder_watcher"),
        ("S3", "s3"),
        ("GCS", "gcs"),
        ("GOOGLE_DRIVE", "google_drive"),
    ],
    "jobtype": [
        ("INGEST", "ingest"),
        ("NORMALIZE", "normalize"),
        ("TAG", "tag"),
        ("DESCRIBE", "describe"),
        ("EMBED", "embed"),
        ("CLUSTER", "cluster"),
        ("SUMMARIZE_CLUSTER", "summarize_cluster"),
        ("FULL_PIPELINE", "full_pipeline"),
        ("REPROCESS", "reprocess"),
        ("BATCH_REPROCESS", "batch_reprocess"),
        ("LORA_TRAIN", "lora_train"),
        ("GENERATE_IMAGE", "generate_image"),
        ("BATCH_GENERATE", "batch_generate"),
        ("LORA_EVALUATE", "lora_evaluate"),
    ],
    "jobstatus": [
        ("PENDING", "pending"),
        ("RUNNING", "running"),
        ("COMPLETED", "completed"),
        ("FAILED", "failed"),
        ("CANCELLED", "cancelled"),
    ],
}


def upgrade() -> None:
    for enum_type, renames in ENUM_RENAMES.items():
        for old_val, new_val in renames:
            # Only rename if the old (uppercase) value exists
            op.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_enum
                        WHERE enumlabel = '{old_val}'
                        AND enumtypid = (SELECT oid FROM pg_type WHERE typname = '{enum_type}')
                    ) THEN
                        ALTER TYPE {enum_type} RENAME VALUE '{old_val}' TO '{new_val}';
                    END IF;
                END
                $$;
            """)


def downgrade() -> None:
    for enum_type, renames in ENUM_RENAMES.items():
        for old_val, new_val in renames:
            op.execute(f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM pg_enum
                        WHERE enumlabel = '{new_val}'
                        AND enumtypid = (SELECT oid FROM pg_type WHERE typname = '{enum_type}')
                    ) THEN
                        ALTER TYPE {enum_type} RENAME VALUE '{new_val}' TO '{old_val}';
                    END IF;
                END
                $$;
            """)
