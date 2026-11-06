"""add storage_path column to video_releases table

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-05
Author: migration script

This migration adds the storage_path column which allows releases to be identified
by their human-readable name rather than UUID in the filesystem.

The storage_path defaults to the release id (UUID) for backward compatibility,
so existing deployments continue working without code changes.
"""

from alembic import op
import sqlalchemy as sa


# Revision identifiers
revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add storage_path column and set defaults for existing releases."""
    
    # Add new column (nullable initially, will be populated by application logic)
    op.add_column('video_releases', sa.Column(
        'storage_path',
        sa.String(255),
        nullable=True,
        comment='Path component for release folder (defaults to id for backward compatibility)'
    ))
    
    # For new releases created after migration, storage_path will be set by application
    # Existing releases get null value (application will use id as fallback)


def downgrade() -> None:
    """Remove storage_path column and restore to UUID-based paths."""
    op.drop_column('video_releases', 'storage_path')
