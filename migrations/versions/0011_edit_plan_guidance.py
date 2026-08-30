"""Add Project edit recommendations and producer edit choices.

Revision ID: 0011_edit_plan_guidance
Revises: 0010_release_production_memory
Create Date: 2026-08-29
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0011_edit_plan_guidance"
down_revision: str | None = "0010_release_production_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "producer_workspaces",
        sa.Column("edit_plan_document_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "producer_workspaces",
        sa.Column("edit_plan_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "producer_workspaces",
        sa.Column("edit_plan_imported_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column("edit_motion_recommendation_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column("edit_transition_recommendation_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column("producer_motion_type", sa.String(24), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column("producer_motion_target", sa.Text(), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column("producer_transition_type", sa.String(24), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column("edit_guidance_asset_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column(
            "edit_guidance_needs_review",
            sa.Boolean(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("producer_beats", "edit_guidance_needs_review")
    op.drop_column("producer_beats", "edit_guidance_asset_sha256")
    op.drop_column("producer_beats", "producer_transition_type")
    op.drop_column("producer_beats", "producer_motion_target")
    op.drop_column("producer_beats", "producer_motion_type")
    op.drop_column("producer_beats", "edit_transition_recommendation_json")
    op.drop_column("producer_beats", "edit_motion_recommendation_json")
    op.drop_column("producer_workspaces", "edit_plan_imported_at")
    op.drop_column("producer_workspaces", "edit_plan_json")
    op.drop_column("producer_workspaces", "edit_plan_document_sha256")
