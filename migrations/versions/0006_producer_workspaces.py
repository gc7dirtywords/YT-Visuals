"""Add producer-led visual plan workspaces.

Revision ID: 0006_producer_workspaces
Revises: 0005_visual_workflow
Create Date: 2026-08-25
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_producer_workspaces"
down_revision: str | None = "0005_visual_workflow"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "producer_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("story_external_id", sa.String(128, collation="NOCASE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("plan_document_sha256", sa.String(64), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("status IN ('active', 'complete')", name=op.f("ck_producer_workspaces_status")),
        sa.CheckConstraint("length(trim(story_external_id)) > 0", name=op.f("ck_producer_workspaces_story_external_id_not_empty")),
        sa.CheckConstraint("length(trim(title)) > 0", name=op.f("ck_producer_workspaces_title_not_empty")),
        sa.CheckConstraint("length(plan_document_sha256) = 64", name=op.f("ck_producer_workspaces_plan_sha256_length")),
        sa.UniqueConstraint("story_external_id", name=op.f("uq_producer_workspaces_story_external_id")),
    )
    op.create_table(
        "producer_beats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("external_beat_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("specification_json", sa.JSON(), nullable=False),
        sa.Column("selected_asset_id", sa.Integer()),
        sa.Column("selected_asset_sha256", sa.String(64)),
        sa.Column("selected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_producer_beats_sequence_positive")),
        sa.CheckConstraint("selected_asset_sha256 IS NULL OR length(selected_asset_sha256) = 64", name=op.f("ck_producer_beats_selected_sha256_length")),
        sa.ForeignKeyConstraint(["workspace_id"], ["producer_workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["selected_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workspace_id", "external_beat_id", name="uq_producer_beats_workspace_external"),
        sa.UniqueConstraint("workspace_id", "sequence", name="uq_producer_beats_workspace_sequence"),
    )
    op.create_index("ix_producer_beats_workspace_sequence", "producer_beats", ["workspace_id", "sequence"])
    op.create_table(
        "producer_beat_hidden_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("beat_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.ForeignKeyConstraint(["beat_id"], ["producer_beats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("beat_id", "asset_id", name="uq_producer_hidden_beat_asset"),
    )
    op.create_index("ix_producer_hidden_beat", "producer_beat_hidden_assets", ["beat_id"])


def downgrade() -> None:
    op.drop_index("ix_producer_hidden_beat", table_name="producer_beat_hidden_assets")
    op.drop_table("producer_beat_hidden_assets")
    op.drop_index("ix_producer_beats_workspace_sequence", table_name="producer_beats")
    op.drop_table("producer_beats")
    op.drop_table("producer_workspaces")
