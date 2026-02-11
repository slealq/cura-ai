"""Add app_settings table.

Revision ID: 002_add_app_settings
Revises: 001_initial
Create Date: 2024-01-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '002_add_app_settings'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create app_settings table
    op.create_table(
        'app_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_app_settings_id', 'app_settings', ['id'])
    op.create_index('ix_app_settings_key', 'app_settings', ['key'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_app_settings_key', table_name='app_settings')
    op.drop_index('ix_app_settings_id', table_name='app_settings')
    op.drop_table('app_settings')

