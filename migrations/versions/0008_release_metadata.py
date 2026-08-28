"""Add lifecycle metadata to video releases.

Revision ID: 0008_release_metadata
Revises: 0007_workspace_organization
Create Date: 2026-08-28
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_release_metadata"
down_revision: str | None = "0007_workspace_organization"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The real catalog is already at 0007 and contains recovered producer beats.
    # Additive columns on video_releases leave producer_workspaces and its children untouched.
    op.add_column(
        "video_releases",
        sa.Column("status", sa.String(16), nullable=False, server_default="planned"),
    )
    op.add_column("video_releases", sa.Column("release_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("video_releases", "release_date")
    op.drop_column("video_releases", "status")
