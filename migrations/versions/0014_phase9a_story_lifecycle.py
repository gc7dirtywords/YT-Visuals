"""Add Phase 9A story lifecycle and visual plan revisions.

Revision ID: 0014_phase9a_story_lifecycle
Revises: 0013_release_production_artifacts
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0014_phase9a_story_lifecycle"
down_revision = "0013_release_production_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("producer_workspaces", sa.Column("archived_at", sa.DateTime(timezone=True)))
    op.add_column("producer_workspaces", sa.Column("current_plan_revision_id", sa.String(36)))
    op.add_column("producer_beats", sa.Column("retired_at", sa.DateTime(timezone=True)))
    op.add_column("producer_beats", sa.Column("plan_needs_review", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    op.create_table(
        "producer_visual_plan_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), sa.ForeignKey("producer_workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("original_plan_json", sa.JSON(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("change_note", sa.Text()),
        sa.CheckConstraint("revision > 0", name="ck_producer_plan_revision_positive"),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_producer_plan_revision_sha256_length"),
        sa.UniqueConstraint("workspace_id", "revision", name="uq_producer_plan_revision_workspace_revision"),
    )
    op.create_index("ix_producer_plan_revision_workspace", "producer_visual_plan_revisions", ["workspace_id", "revision"])
    op.execute("""
        INSERT INTO producer_visual_plan_revisions (id, workspace_id, revision, original_plan_json, source_sha256)
        SELECT lower(hex(randomblob(16))), id, 1, plan_json, plan_document_sha256 FROM producer_workspaces
    """)
    op.execute("""
        UPDATE producer_workspaces SET current_plan_revision_id = (
          SELECT id FROM producer_visual_plan_revisions r WHERE r.workspace_id = producer_workspaces.id AND r.revision = 1
        )
    """)
    with op.batch_alter_table("producer_beats", recreate="always") as batch:
        batch.drop_constraint("uq_producer_beats_workspace_sequence", type_="unique")
    op.create_index("uq_producer_beats_active_workspace_sequence", "producer_beats", ["workspace_id", "sequence"], unique=True, sqlite_where=sa.text("retired_at IS NULL"))
    op.execute("CREATE TRIGGER trg_producer_plan_revisions_no_update BEFORE UPDATE ON producer_visual_plan_revisions BEGIN SELECT RAISE(ABORT, 'visual plan revisions are immutable'); END")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_producer_plan_revisions_no_update")
    op.drop_index("uq_producer_beats_active_workspace_sequence", table_name="producer_beats")
    with op.batch_alter_table("producer_beats", recreate="always") as batch:
        batch.create_unique_constraint("uq_producer_beats_workspace_sequence", ["workspace_id", "sequence"])
    op.drop_index("ix_producer_plan_revision_workspace", table_name="producer_visual_plan_revisions")
    op.drop_table("producer_visual_plan_revisions")
    op.drop_column("producer_beats", "plan_needs_review")
    op.drop_column("producer_beats", "retired_at")
    op.drop_column("producer_workspaces", "current_plan_revision_id")
    op.drop_column("producer_workspaces", "archived_at")
