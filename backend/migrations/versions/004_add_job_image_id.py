"""Add image_id to jobs table.

Revision ID: 004_add_job_image_id
Revises: 003_flatten_tags_remove_caption
Create Date: 2024-01-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '004_add_job_image_id'
down_revision: Union[str, None] = '003_flatten_tags_remove_caption'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('jobs', sa.Column('image_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_jobs_image_id', 'jobs', 'images',
        ['image_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index('ix_jobs_image_id', 'jobs', ['image_id'])


def downgrade() -> None:
    op.drop_index('ix_jobs_image_id', table_name='jobs')
    op.drop_constraint('fk_jobs_image_id', 'jobs', type_='foreignkey')
    op.drop_column('jobs', 'image_id')
