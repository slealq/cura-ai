"""Permanent image history and indexed library ancestry."""
import sqlalchemy as sa
from alembic import op

revision = "057_image_history"
down_revision = "056_library_generated_images"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'image_delete'")
    for table in ("images", "generated_images"):
        op.add_column(table, sa.Column("history", sa.JSON(), nullable=True))
    op.create_table(
        "image_history_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("result_image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_image_id", sa.Integer(), sa.ForeignKey("images.id", ondelete="SET NULL")),
        sa.Column("result_key", sa.String(512), nullable=False),
        sa.Column("source_key", sa.String(512), nullable=False),
        sa.UniqueConstraint("result_key", "source_key"),
    )
    for col in ("user_id", "result_image_id", "source_image_id"):
        op.create_index(f"ix_image_history_links_{col}", "image_history_links", [col])


def downgrade():
    # PostgreSQL cannot remove enum values; image_delete remains unused.
    op.drop_table("image_history_links")
    for table in ("generated_images", "images"):
        op.drop_column(table, "history")
