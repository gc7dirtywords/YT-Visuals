"""Add versioned release production artifacts.

Revision ID: 0013_release_production_artifacts
Revises: 0012_story_documents
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision = "0013_release_production_artifacts"
down_revision = "0012_story_documents"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "release_production_artifact_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("video_release_id", sa.String(36), sa.ForeignKey("video_releases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("technical_metadata", sa.JSON()),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.CheckConstraint("artifact_type IN ('resolve_project', 'final_render', 'other')", name="ck_release_artifact_type"),
        sa.CheckConstraint("version > 0", name="ck_release_artifact_version_positive"),
        sa.CheckConstraint("length(trim(original_filename)) > 0", name="ck_release_artifact_original_filename_not_empty"),
        sa.CheckConstraint("length(trim(stored_filename)) > 0", name="ck_release_artifact_stored_filename_not_empty"),
        sa.CheckConstraint("length(sha256) = 64", name="ck_release_artifact_sha256_length"),
        sa.CheckConstraint("sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_release_artifact_sha256_lower_hex"),
        sa.CheckConstraint("file_size_bytes >= 0", name="ck_release_artifact_file_size_nonnegative"),
        sa.UniqueConstraint("video_release_id", "artifact_type", "version", name="uq_release_artifact_release_type_version"),
        sa.UniqueConstraint("video_release_id", "stored_filename", name="uq_release_artifact_release_stored_filename"),
    )
    op.create_index("ix_release_artifact_release_type_version", "release_production_artifact_versions", ["video_release_id", "artifact_type", "version"])
    op.execute("CREATE TRIGGER trg_release_artifact_versions_no_update BEFORE UPDATE ON release_production_artifact_versions BEGIN SELECT RAISE(ABORT, 'release artifact versions are immutable'); END")

def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_release_artifact_versions_no_update")
    op.drop_index("ix_release_artifact_release_type_version", table_name="release_production_artifact_versions")
    op.drop_table("release_production_artifact_versions")
