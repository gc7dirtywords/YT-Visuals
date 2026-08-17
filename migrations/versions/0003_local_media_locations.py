"""Add local media paths and availability history.

Revision ID: 0003_local_locations
Revises: 0002_download_history
Create Date: 2026-08-16
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_local_locations"
down_revision: str | None = "0002_download_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TIMESTAMP = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "media_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("media_asset_id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.String(1024, collation="NOCASE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="available"),
        sa.Column("provenance_type", sa.String(32), nullable=False),
        sa.Column("file_size_bytes", sa.Integer()),
        sa.Column("file_modified_ns", sa.Integer()),
        sa.Column("file_modified_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("missing_since", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("status IN ('available', 'missing')", name=op.f("ck_media_locations_status")),
        sa.CheckConstraint(
            "provenance_type IN ('local_import', 'provider_download')",
            name=op.f("ck_media_locations_provenance_type"),
        ),
        sa.CheckConstraint(
            "length(trim(relative_path)) > 0",
            name=op.f("ck_media_locations_relative_path_not_empty"),
        ),
        sa.CheckConstraint(
            "relative_path NOT LIKE '/%'",
            name=op.f("ck_media_locations_relative_path_not_posix_absolute"),
        ),
        sa.CheckConstraint(
            "relative_path NOT GLOB '[A-Za-z]:*'",
            name=op.f("ck_media_locations_relative_path_not_drive_absolute"),
        ),
        sa.CheckConstraint(
            "substr(relative_path, 1, 1) != char(92)",
            name=op.f("ck_media_locations_relative_path_not_backslash_absolute"),
        ),
        sa.CheckConstraint(
            "file_size_bytes IS NULL OR file_size_bytes >= 0",
            name=op.f("ck_media_locations_file_size_nonnegative"),
        ),
        sa.CheckConstraint(
            "file_modified_ns IS NULL OR file_modified_ns >= 0",
            name=op.f("ck_media_locations_modified_ns_nonnegative"),
        ),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("relative_path", name=op.f("uq_media_locations_relative_path")),
    )
    op.create_index(
        "ix_media_locations_asset_status", "media_locations", ["media_asset_id", "status"]
    )
    op.create_index(
        "ix_media_locations_status_last_seen", "media_locations", ["status", "last_seen_at"]
    )


def downgrade() -> None:
    op.drop_table("media_locations")
