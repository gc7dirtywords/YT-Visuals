"""Add persistent media download and acquisition history.

Revision ID: 0002_download_history
Revises: 0001_initial
Create Date: 2026-08-16
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_download_history"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TIMESTAMP = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "media_downloads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(100, collation="NOCASE"), nullable=False),
        sa.Column("provider_asset_id", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("download_url", sa.String(4096)),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False, server_default="started"),
        sa.Column("media_asset_id", sa.Integer()),
        sa.Column("relative_path", sa.String(1024)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("downloaded_bytes", sa.Integer()),
        sa.Column("http_status_code", sa.Integer()),
        sa.Column("content_type", sa.String(255)),
        sa.Column("error_category", sa.String(100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("provider_metadata", sa.JSON()),
        sa.Column("request_metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("media_type IN ('image', 'video')", name=op.f("ck_media_downloads_media_type")),
        sa.CheckConstraint(
            "status IN ('started', 'success', 'failed', 'duplicate', 'reused')",
            name=op.f("ck_media_downloads_status"),
        ),
        sa.CheckConstraint(
            "length(trim(provider)) > 0", name=op.f("ck_media_downloads_provider_not_empty")
        ),
        sa.CheckConstraint(
            "length(trim(provider_asset_id)) > 0",
            name=op.f("ck_media_downloads_provider_asset_id_not_empty"),
        ),
        sa.CheckConstraint(
            "downloaded_bytes IS NULL OR downloaded_bytes >= 0",
            name=op.f("ck_media_downloads_bytes_nonnegative"),
        ),
        sa.CheckConstraint(
            "http_status_code IS NULL OR http_status_code BETWEEN 100 AND 599",
            name=op.f("ck_media_downloads_http_status_range"),
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64",
            name=op.f("ck_media_downloads_sha256_length"),
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR sha256 NOT GLOB '*[^0-9a-f]*'",
            name=op.f("ck_media_downloads_sha256_lower_hex"),
        ),
        sa.CheckConstraint(
            "relative_path IS NULL OR relative_path NOT LIKE '/%'",
            name=op.f("ck_media_downloads_path_not_posix_absolute"),
        ),
        sa.CheckConstraint(
            "relative_path IS NULL OR relative_path NOT GLOB '[A-Za-z]:*'",
            name=op.f("ck_media_downloads_path_not_drive_absolute"),
        ),
        sa.CheckConstraint(
            "relative_path IS NULL OR substr(relative_path, 1, 1) != char(92)",
            name=op.f("ck_media_downloads_path_not_backslash_absolute"),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= attempted_at",
            name=op.f("ck_media_downloads_completed_after_attempted"),
        ),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_media_downloads_provider_asset_attempted",
        "media_downloads",
        ["provider", "provider_asset_id", "attempted_at"],
    )
    op.create_index(
        "ix_media_downloads_status_attempted", "media_downloads", ["status", "attempted_at"]
    )
    op.create_index("ix_media_downloads_media_asset_id", "media_downloads", ["media_asset_id"])
    op.create_index("ix_media_downloads_sha256", "media_downloads", ["sha256"])


def downgrade() -> None:
    op.drop_table("media_downloads")
