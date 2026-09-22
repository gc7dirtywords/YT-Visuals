"""Allow versioned story narration audio artifacts.

Revision ID: 0015_story_narration_audio
Revises: 0014_phase9a_story_lifecycle
"""
from __future__ import annotations

from alembic import op

revision = "0015_story_narration_audio"
down_revision = "0014_phase9a_story_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("story_document_versions", recreate="always") as batch:
        batch.drop_constraint("document_type", type_="check")
        batch.create_check_constraint(
            "document_type",
            "document_type IN ('narration_script', 'narrator_copy', 'subtitles', 'narration_audio', 'other')",
        )
    op.execute(
        "CREATE TRIGGER trg_story_document_versions_no_update BEFORE UPDATE "
        "ON story_document_versions BEGIN SELECT RAISE(ABORT, 'story document versions are immutable'); END"
    )


def downgrade() -> None:
    with op.batch_alter_table("story_document_versions", recreate="always") as batch:
        batch.drop_constraint("document_type", type_="check")
        batch.create_check_constraint(
            "document_type",
            "document_type IN ('narration_script', 'narrator_copy', 'subtitles', 'other')",
        )
    op.execute(
        "CREATE TRIGGER trg_story_document_versions_no_update BEFORE UPDATE "
        "ON story_document_versions BEGIN SELECT RAISE(ABORT, 'story document versions are immutable'); END"
    )
