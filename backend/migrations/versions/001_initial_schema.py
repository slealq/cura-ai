"""Initial schema with all tables.

Revision ID: 001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create images table
    op.create_table(
        'images',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source', sa.Enum('upload', 'folder_watcher', 's3', 'gcs', 'google_drive', name='imagesource'), nullable=False),
        sa.Column('original_uri', sa.String(length=1024), nullable=True),
        sa.Column('object_key', sa.String(length=512), nullable=False),
        sa.Column('original_filename', sa.String(length=512), nullable=True),
        sa.Column('file_hash', sa.String(length=64), nullable=False),
        sa.Column('perceptual_hash', sa.String(length=64), nullable=True),
        sa.Column('width', sa.Integer(), nullable=True),
        sa.Column('height', sa.Integer(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('mime_type', sa.String(length=64), nullable=True),
        sa.Column('thumbnail_uri_small', sa.String(length=512), nullable=True),
        sa.Column('thumbnail_uri_medium', sa.String(length=512), nullable=True),
        sa.Column('thumbnail_uri_large', sa.String(length=512), nullable=True),
        sa.Column('status', sa.Enum('pending', 'ingested', 'normalized', 'tagged', 'described', 'embedded', 'clustered', 'failed', name='imagestatus'), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('ingested_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_images_id', 'images', ['id'])
    op.create_index('ix_images_file_hash', 'images', ['file_hash'], unique=True)
    op.create_index('ix_images_perceptual_hash', 'images', ['perceptual_hash'])
    op.create_index('ix_images_status_created', 'images', ['status', 'created_at'])
    op.create_index('ix_images_source_status', 'images', ['source', 'status'])
    op.create_unique_constraint('uq_images_object_key', 'images', ['object_key'])

    # Create image_metadata table
    op.create_table(
        'image_metadata',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('image_id', sa.Integer(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=False, default={}),
        sa.Column('dominant_colors', sa.JSON(), nullable=False, default=[]),
        sa.Column('caption_short', sa.Text(), nullable=True),
        sa.Column('description_long', sa.Text(), nullable=True),
        sa.Column('embedding', Vector(1536), nullable=True),
        sa.Column('tagging_model', sa.String(length=128), nullable=True),
        sa.Column('caption_model', sa.String(length=128), nullable=True),
        sa.Column('embedding_model', sa.String(length=128), nullable=True),
        sa.Column('tagging_prompt_version', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_image_metadata_id', 'image_metadata', ['id'])
    op.create_unique_constraint('uq_image_metadata_image_id', 'image_metadata', ['image_id'])

    # Create clusters table
    op.create_table(
        'clusters',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('method', sa.Enum('hdbscan', 'kmeans', 'graph', name='clusteringmethod'), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('centroid_embedding', Vector(1536), nullable=True),
        sa.Column('size', sa.Integer(), nullable=False, default=0),
        sa.Column('summary_title', sa.String(length=256), nullable=True),
        sa.Column('summary_description', sa.Text(), nullable=True),
        sa.Column('common_tags', sa.JSON(), nullable=False, default={}),
        sa.Column('representative_image_ids', sa.JSON(), nullable=False, default=[]),
        sa.Column('display_name', sa.String(length=256), nullable=True),
        sa.Column('is_pinned', sa.Boolean(), nullable=False, default=False),
        sa.Column('is_archived', sa.Boolean(), nullable=False, default=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('summarization_model', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_clusters_id', 'clusters', ['id'])
    op.create_index('ix_clusters_run_id_size', 'clusters', ['run_id', 'size'])
    op.create_index('ix_clusters_pinned_archived', 'clusters', ['is_pinned', 'is_archived'])

    # Create cluster_memberships table
    op.create_table(
        'cluster_memberships',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cluster_id', sa.Integer(), nullable=False),
        sa.Column('image_id', sa.Integer(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False, default=1.0),
        sa.Column('distance_to_centroid', sa.Float(), nullable=True),
        sa.Column('is_outlier', sa.Boolean(), nullable=False, default=False),
        sa.Column('is_excluded', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['cluster_id'], ['clusters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['image_id'], ['images.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_cluster_memberships_id', 'cluster_memberships', ['id'])
    op.create_index('ix_cluster_memberships_cluster_score', 'cluster_memberships', ['cluster_id', 'score'])
    op.create_index('ix_cluster_memberships_image', 'cluster_memberships', ['image_id'])

    # Create jobs table
    op.create_table(
        'jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('celery_task_id', sa.String(length=64), nullable=True),
        sa.Column('job_type', sa.Enum('ingest', 'normalize', 'tag', 'describe', 'embed', 'cluster', 'summarize_cluster', 'full_pipeline', 'reprocess', name='jobtype'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'running', 'completed', 'failed', 'cancelled', name='jobstatus'), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False, default=0),
        sa.Column('total_items', sa.Integer(), nullable=False, default=0),
        sa.Column('parameters', sa.JSON(), nullable=False, default={}),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('logs', sa.JSON(), nullable=False, default=[]),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_id', 'jobs', ['id'])
    op.create_index('ix_jobs_celery_task_id', 'jobs', ['celery_task_id'])
    op.create_index('ix_jobs_status_created', 'jobs', ['status', 'created_at'])
    op.create_index('ix_jobs_type_status', 'jobs', ['job_type', 'status'])

    # Create vector index for similarity search
    op.execute('''
        CREATE INDEX ix_image_metadata_embedding
        ON image_metadata
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    ''')


def downgrade() -> None:
    op.drop_table('cluster_memberships')
    op.drop_table('clusters')
    op.drop_table('image_metadata')
    op.drop_table('jobs')
    op.drop_table('images')

    # Drop enums
    op.execute('DROP TYPE IF EXISTS jobstatus')
    op.execute('DROP TYPE IF EXISTS jobtype')
    op.execute('DROP TYPE IF EXISTS clusteringmethod')
    op.execute('DROP TYPE IF EXISTS imagestatus')
    op.execute('DROP TYPE IF EXISTS imagesource')
