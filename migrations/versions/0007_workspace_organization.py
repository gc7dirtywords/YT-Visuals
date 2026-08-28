"""Add producer workspace lifecycle and video release organization.

Revision ID: 0007_workspace_organization
Revises: 0006_producer_workspaces
Create Date: 2026-08-28
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_workspace_organization"
down_revision: str | None = "0006_producer_workspaces"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
TIMESTAMP = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "video_releases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255, collation="NOCASE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_video_releases_name_not_empty")),
        sa.UniqueConstraint("name", name=op.f("uq_video_releases_name")),
    )
    op.execute("""CREATE TABLE producer_workspaces_0007 (
        id VARCHAR(36) NOT NULL PRIMARY KEY, story_external_id VARCHAR(128) COLLATE NOCASE NOT NULL,
        title VARCHAR(255) NOT NULL, plan_document_sha256 VARCHAR(64) NOT NULL, plan_json JSON NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'in_production', video_release_id VARCHAR(36), release_position INTEGER,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_producer_workspaces_status CHECK (status IN ('planned', 'in_production', 'completed')),
        CONSTRAINT ck_producer_workspaces_story_external_id_not_empty CHECK (length(trim(story_external_id)) > 0),
        CONSTRAINT ck_producer_workspaces_title_not_empty CHECK (length(trim(title)) > 0),
        CONSTRAINT ck_producer_workspaces_plan_sha256_length CHECK (length(plan_document_sha256) = 64),
        CONSTRAINT uq_producer_workspaces_story_external_id UNIQUE (story_external_id),
        FOREIGN KEY(video_release_id) REFERENCES video_releases(id) ON DELETE RESTRICT
    )""")
    op.execute("""INSERT INTO producer_workspaces_0007 (id, story_external_id, title, plan_document_sha256, plan_json, status, created_at, updated_at)
        SELECT id, story_external_id, title, plan_document_sha256, plan_json,
        CASE status WHEN 'complete' THEN 'completed' ELSE 'in_production' END, created_at, updated_at FROM producer_workspaces""")
    # Dropping the parent table fires the existing ON DELETE CASCADE foreign keys.
    # Preserve producer children explicitly so stable workspace/beat identities survive.
    op.execute("CREATE TABLE producer_beats_0007_backup AS SELECT * FROM producer_beats")
    op.execute("CREATE TABLE producer_hidden_0007_backup AS SELECT * FROM producer_beat_hidden_assets")
    op.drop_table("producer_workspaces")
    op.rename_table("producer_workspaces_0007", "producer_workspaces")
    op.execute("""INSERT INTO producer_beats
        (id, workspace_id, external_beat_id, sequence, specification_json,
         selected_asset_id, selected_asset_sha256, selected_at, created_at, updated_at)
        SELECT id, workspace_id, external_beat_id, sequence, specification_json,
         selected_asset_id, selected_asset_sha256, selected_at, created_at, updated_at
        FROM producer_beats_0007_backup""")
    op.execute("""INSERT INTO producer_beat_hidden_assets
        (id, beat_id, asset_id, hidden_at, created_at, updated_at)
        SELECT id, beat_id, asset_id, hidden_at, created_at, updated_at
        FROM producer_hidden_0007_backup""")
    op.drop_table("producer_hidden_0007_backup")
    op.drop_table("producer_beats_0007_backup")
    op.create_index("ix_producer_workspaces_release_position", "producer_workspaces", ["video_release_id", "release_position"])


def downgrade() -> None:
    op.drop_index("ix_producer_workspaces_release_position", table_name="producer_workspaces")
    op.execute("""CREATE TABLE producer_workspaces_0006 (
        id VARCHAR(36) NOT NULL PRIMARY KEY, story_external_id VARCHAR(128) COLLATE NOCASE NOT NULL UNIQUE,
        title VARCHAR(255) NOT NULL, plan_document_sha256 VARCHAR(64) NOT NULL, plan_json JSON NOT NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'active', created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT ck_producer_workspaces_status CHECK (status IN ('active', 'complete')),
        CONSTRAINT ck_producer_workspaces_story_external_id_not_empty CHECK (length(trim(story_external_id)) > 0),
        CONSTRAINT ck_producer_workspaces_title_not_empty CHECK (length(trim(title)) > 0),
        CONSTRAINT ck_producer_workspaces_plan_sha256_length CHECK (length(plan_document_sha256) = 64)
    )""")
    op.execute("""INSERT INTO producer_workspaces_0006 (id, story_external_id, title, plan_document_sha256, plan_json, status, created_at, updated_at)
        SELECT id, story_external_id, title, plan_document_sha256, plan_json,
        CASE status WHEN 'completed' THEN 'complete' ELSE 'active' END, created_at, updated_at FROM producer_workspaces""")
    op.execute("CREATE TABLE producer_beats_0006_backup AS SELECT * FROM producer_beats")
    op.execute("CREATE TABLE producer_hidden_0006_backup AS SELECT * FROM producer_beat_hidden_assets")
    op.drop_table("producer_workspaces")
    op.rename_table("producer_workspaces_0006", "producer_workspaces")
    op.execute("""INSERT INTO producer_beats
        (id, workspace_id, external_beat_id, sequence, specification_json,
         selected_asset_id, selected_asset_sha256, selected_at, created_at, updated_at)
        SELECT id, workspace_id, external_beat_id, sequence, specification_json,
         selected_asset_id, selected_asset_sha256, selected_at, created_at, updated_at
        FROM producer_beats_0006_backup""")
    op.execute("""INSERT INTO producer_beat_hidden_assets
        (id, beat_id, asset_id, hidden_at, created_at, updated_at)
        SELECT id, beat_id, asset_id, hidden_at, created_at, updated_at
        FROM producer_hidden_0006_backup""")
    op.drop_table("producer_hidden_0006_backup")
    op.drop_table("producer_beats_0006_backup")
    op.drop_table("video_releases")
