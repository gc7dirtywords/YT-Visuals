"""Create the initial visual asset catalog schema.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-08-16
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TIMESTAMP = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "media_providers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100, collation="NOCASE"), nullable=False),
        sa.Column("website_url", sa.String(2048)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_media_providers_name_not_empty")),
        sa.UniqueConstraint("name", name="uq_media_providers_name"),
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("relative_path", sa.String(1024), nullable=False),
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("title", sa.String(255)),
        sa.Column("description", sa.Text()),
        sa.Column("mime_type", sa.String(127)),
        sa.Column("file_size_bytes", sa.Integer()),
        sa.Column("sha256", sa.String(64)),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("file_modified_at", sa.DateTime(timezone=True)),
        sa.Column("captured_at", sa.DateTime(timezone=True)),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("technical_metadata", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("media_type IN ('image', 'video')", name=op.f("ck_media_assets_media_type")),
        sa.CheckConstraint("status IN ('active', 'archived', 'missing')", name=op.f("ck_media_assets_status")),
        sa.CheckConstraint("length(trim(relative_path)) > 0", name=op.f("ck_media_assets_relative_path_not_empty")),
        sa.CheckConstraint("relative_path NOT LIKE '/%'", name=op.f("ck_media_assets_relative_path_not_posix_absolute")),
        sa.CheckConstraint("relative_path NOT GLOB '[A-Za-z]:*'", name=op.f("ck_media_assets_relative_path_not_drive_absolute")),
        sa.CheckConstraint("substr(relative_path, 1, 1) != char(92)", name=op.f("ck_media_assets_relative_path_not_backslash_absolute")),
        sa.CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name=op.f("ck_media_assets_file_size_nonnegative")),
        sa.CheckConstraint("width IS NULL OR width > 0", name=op.f("ck_media_assets_width_positive")),
        sa.CheckConstraint("height IS NULL OR height > 0", name=op.f("ck_media_assets_height_positive")),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name=op.f("ck_media_assets_duration_nonnegative")),
        sa.CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name=op.f("ck_media_assets_sha256_length")),
        sa.CheckConstraint("sha256 IS NULL OR sha256 NOT GLOB '*[^0-9a-f]*'", name=op.f("ck_media_assets_sha256_lower_hex")),
        sa.CheckConstraint("usage_count >= 0", name=op.f("ck_media_assets_usage_count_nonnegative")),
        sa.UniqueConstraint("relative_path", name="uq_media_assets_relative_path"),
        sa.UniqueConstraint("sha256", name="uq_media_assets_sha256"),
    )
    op.create_index("ix_media_assets_type_status", "media_assets", ["media_type", "status"])
    op.create_index("ix_media_assets_last_used_at", "media_assets", ["last_used_at"])

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100, collation="NOCASE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_tags_name_not_empty")),
        sa.UniqueConstraint("name", name="uq_tags_name"),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(150, collation="NOCASE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("season_number", sa.Integer()),
        sa.Column("episode_number", sa.Integer()),
        sa.Column("status", sa.String(20), nullable=False, server_default="planning"),
        sa.Column("project_path", sa.String(1024)),
        sa.Column("planned_publish_date", sa.Date()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("length(trim(slug)) > 0", name=op.f("ck_projects_slug_not_empty")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_projects_title_not_empty")),
        sa.CheckConstraint("status IN ('planning', 'in_progress', 'complete', 'published', 'archived')", name=op.f("ck_projects_status")),
        sa.CheckConstraint("season_number IS NULL OR season_number > 0", name=op.f("ck_projects_season_positive")),
        sa.CheckConstraint("episode_number IS NULL OR episode_number > 0", name=op.f("ck_projects_episode_positive")),
        sa.CheckConstraint("project_path IS NULL OR project_path NOT LIKE '/%'", name=op.f("ck_projects_path_not_posix_absolute")),
        sa.CheckConstraint("project_path IS NULL OR project_path NOT GLOB '[A-Za-z]:*'", name=op.f("ck_projects_path_not_drive_absolute")),
        sa.CheckConstraint("project_path IS NULL OR substr(project_path, 1, 1) != char(92)", name=op.f("ck_projects_path_not_backslash_absolute")),
        sa.UniqueConstraint("slug", name="uq_projects_slug"),
        sa.UniqueConstraint("season_number", "episode_number", name="uq_projects_season_episode"),
    )

    op.create_table(
        "media_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer()),
        sa.Column("provider_asset_id", sa.String(255)),
        sa.Column("source_url", sa.String(2048)),
        sa.Column("creator_name", sa.String(255)),
        sa.Column("creator_url", sa.String(2048)),
        sa.Column("original_filename", sa.String(512)),
        sa.Column("acquired_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_id"], ["media_providers.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("provider_id", "provider_asset_id", name="uq_media_sources_provider_asset"),
    )
    op.create_index("ix_media_sources_asset_id", "media_sources", ["asset_id"])

    op.create_table(
        "asset_licenses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("license_name", sa.String(255)),
        sa.Column("license_url", sa.String(2048)),
        sa.Column("attribution_required", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("attribution_text", sa.Text()),
        sa.Column("usage_terms", sa.Text()),
        sa.Column("commercial_use_allowed", sa.Boolean()),
        sa.Column("modifications_allowed", sa.Boolean()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("asset_id", name="uq_asset_licenses_asset_id"),
    )

    op.create_table(
        "stories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("target_duration_seconds", sa.Integer()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("position > 0", name=op.f("ck_stories_position_positive")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_stories_title_not_empty")),
        sa.CheckConstraint("target_duration_seconds IS NULL OR target_duration_seconds > 0", name=op.f("ck_stories_duration_positive")),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("project_id", "position", name="uq_stories_project_position"),
    )
    op.create_index("ix_stories_project_id", "stories", ["project_id"])

    op.create_table(
        "asset_tags",
        sa.Column("asset_id", sa.Integer(), primary_key=True),
        sa.Column("tag_id", sa.Integer(), primary_key=True),
        sa.Column("tagged_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_asset_tags_tag_id", "asset_tags", ["tag_id"])

    op.create_table(
        "asset_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("segment_label", sa.String(255)),
        sa.Column("narration_start_ms", sa.Integer()),
        sa.Column("narration_end_ms", sa.Integer()),
        sa.Column("usage_role", sa.String(100)),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("narration_start_ms IS NULL OR narration_start_ms >= 0", name=op.f("ck_asset_usages_start_nonnegative")),
        sa.CheckConstraint("narration_end_ms IS NULL OR narration_end_ms >= 0", name=op.f("ck_asset_usages_end_nonnegative")),
        sa.CheckConstraint(
            "narration_start_ms IS NULL OR narration_end_ms IS NULL OR narration_end_ms >= narration_start_ms",
            name=op.f("ck_asset_usages_end_after_start"),
        ),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_asset_usages_asset_used", "asset_usages", ["asset_id", "used_at"])
    op.create_index("ix_asset_usages_story_id", "asset_usages", ["story_id"])

    op.execute(
        """
        CREATE TRIGGER trg_asset_usages_insert
        AFTER INSERT ON asset_usages
        BEGIN
            UPDATE media_assets
            SET usage_count = (SELECT COUNT(*) FROM asset_usages WHERE asset_id = NEW.asset_id),
                last_used_at = (SELECT MAX(used_at) FROM asset_usages WHERE asset_id = NEW.asset_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = NEW.asset_id;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_asset_usages_delete
        AFTER DELETE ON asset_usages
        BEGIN
            UPDATE media_assets
            SET usage_count = (SELECT COUNT(*) FROM asset_usages WHERE asset_id = OLD.asset_id),
                last_used_at = (SELECT MAX(used_at) FROM asset_usages WHERE asset_id = OLD.asset_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = OLD.asset_id;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_asset_usages_update
        AFTER UPDATE OF asset_id, used_at ON asset_usages
        BEGIN
            UPDATE media_assets
            SET usage_count = (SELECT COUNT(*) FROM asset_usages WHERE asset_id = OLD.asset_id),
                last_used_at = (SELECT MAX(used_at) FROM asset_usages WHERE asset_id = OLD.asset_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = OLD.asset_id;
            UPDATE media_assets
            SET usage_count = (SELECT COUNT(*) FROM asset_usages WHERE asset_id = NEW.asset_id),
                last_used_at = (SELECT MAX(used_at) FROM asset_usages WHERE asset_id = NEW.asset_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = NEW.asset_id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_asset_usages_update")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_usages_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_asset_usages_insert")
    op.drop_table("asset_usages")
    op.drop_table("asset_tags")
    op.drop_table("stories")
    op.drop_table("asset_licenses")
    op.drop_table("media_sources")
    op.drop_table("projects")
    op.drop_table("tags")
    op.drop_table("media_assets")
    op.drop_table("media_providers")
