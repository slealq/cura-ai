"""Add search_vector tsvector column with GIN index and auto-update trigger.

Revision ID: 009_add_search_vector
Revises: 008_add_batch_reprocess_job_type
"""
import sqlalchemy as sa
from alembic import op

revision = "009_add_search_vector"
down_revision = "008_add_batch_reprocess_job_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add tsvector column
    op.add_column(
        "image_metadata",
        sa.Column("search_vector", sa.dialects.postgresql.TSVECTOR(), nullable=True),
    )

    # Populate from existing data
    op.execute("""
        UPDATE image_metadata
        SET search_vector = to_tsvector('english',
            COALESCE((
                SELECT string_agg(elem, ' ')
                FROM jsonb_array_elements_text(tags::jsonb) AS elem
            ), '')
            || ' ' ||
            COALESCE(description_long, '')
        )
    """)

    # Create GIN index
    op.create_index(
        "ix_image_metadata_search_vector",
        "image_metadata",
        ["search_vector"],
        postgresql_using="gin",
    )

    # Create trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION update_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector := to_tsvector('english',
                COALESCE((
                    SELECT string_agg(elem, ' ')
                    FROM jsonb_array_elements_text(NEW.tags::jsonb) AS elem
                ), '')
                || ' ' ||
                COALESCE(NEW.description_long, '')
            );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Create trigger
    op.execute("""
        CREATE TRIGGER trg_image_metadata_search_vector
        BEFORE INSERT OR UPDATE OF tags, description_long
        ON image_metadata
        FOR EACH ROW
        EXECUTE FUNCTION update_search_vector();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_image_metadata_search_vector ON image_metadata")
    op.execute("DROP FUNCTION IF EXISTS update_search_vector()")
    op.drop_index("ix_image_metadata_search_vector", table_name="image_metadata")
    op.drop_column("image_metadata", "search_vector")
