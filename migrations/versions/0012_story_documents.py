"""Add immutable versioned story documents.

Revision ID: 0012_story_documents
Revises: 0011_edit_plan_guidance
Create Date: 2026-08-29
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0012_story_documents"
down_revision: str | None = "0011_edit_plan_guidance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "story_document_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("document_type", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("stored_filename", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "document_type IN ('narration_script', 'narrator_copy', 'subtitles', 'other')",
            name=op.f("ck_story_document_versions_document_type"),
        ),
        sa.CheckConstraint(
            "version > 0",
            name=op.f("ck_story_document_versions_version_positive"),
        ),
        sa.CheckConstraint(
            "length(trim(original_filename)) > 0",
            name=op.f("ck_story_document_versions_original_filename_not_empty"),
        ),
        sa.CheckConstraint(
            "length(trim(stored_filename)) > 0",
            name=op.f("ck_story_document_versions_stored_filename_not_empty"),
        ),
        sa.CheckConstraint(
            "length(sha256) = 64",
            name=op.f("ck_story_document_versions_sha256_length"),
        ),
        sa.CheckConstraint(
            "sha256 NOT GLOB '*[^0-9a-f]*'",
            name=op.f("ck_story_document_versions_sha256_lower_hex"),
        ),
        sa.CheckConstraint(
            "file_size_bytes >= 0",
            name=op.f("ck_story_document_versions_file_size_nonnegative"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["producer_workspaces.id"],
            name=op.f("fk_story_document_versions_workspace_id_producer_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_story_document_versions")),
        sa.UniqueConstraint(
            "workspace_id", "document_type", "version",
            name="uq_story_document_workspace_type_version",
        ),
        sa.UniqueConstraint(
            "workspace_id", "stored_filename",
            name="uq_story_document_workspace_stored_filename",
        ),
    )
    op.create_index(
        "ix_story_document_workspace_type_version",
        "story_document_versions",
        ["workspace_id", "document_type", "version"],
        unique=False,
    )
    op.execute(
        "CREATE TRIGGER trg_story_document_versions_no_update BEFORE UPDATE "
        "ON story_document_versions "
        "BEGIN SELECT RAISE(ABORT, 'story document versions are immutable'); END"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_story_document_versions_no_update")
    op.drop_index(
        "ix_story_document_workspace_type_version",
        table_name="story_document_versions",
    )
    op.drop_table("story_document_versions")
