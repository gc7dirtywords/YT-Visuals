"""Add immutable release presentation revisions and production audit events.

Revision ID: 0010_release_production_memory
Revises: 0009_sfx_catalog
Create Date: 2026-08-29
"""

from __future__ import annotations

import json
import uuid
from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0010_release_production_memory"
down_revision: str | None = "0009_sfx_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _insert_event(
    subject_type: str,
    subject_id: str,
    event_type: str,
    payload: dict[str, object],
    *,
    related_subject_type: str | None = None,
    related_subject_id: str | None = None,
) -> None:
    op.get_bind().execute(
        sa.text(
            """INSERT INTO production_events
            (id, subject_type, subject_id, related_subject_type, related_subject_id,
             event_type, source, payload_schema_version, payload_json)
            VALUES (:id, :subject_type, :subject_id, :related_subject_type,
                    :related_subject_id, :event_type, 'migration_0010', 1, :payload_json)"""
        ),
        {
            "id": str(uuid.uuid4()),
            "subject_type": subject_type,
            "subject_id": subject_id,
            "related_subject_type": related_subject_type,
            "related_subject_id": related_subject_id,
            "event_type": event_type,
            "payload_json": json.dumps(payload, sort_keys=True),
        },
    )


def upgrade() -> None:
    op.create_table(
        "release_presentation_revisions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("video_release_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("public_title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("thumbnail_asset_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(40), server_default="producer_ui", nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_release_presentation_revisions_sequence_positive")),
        sa.CheckConstraint(
            "length(trim(public_title)) > 0",
            name=op.f("ck_release_presentation_revisions_public_title_not_empty"),
        ),
        sa.CheckConstraint(
            "length(trim(source)) > 0",
            name=op.f("ck_release_presentation_revisions_source_not_empty"),
        ),
        sa.ForeignKeyConstraint(
            ["thumbnail_asset_id"],
            ["media_assets.id"],
            name=op.f("fk_release_presentation_revisions_thumbnail_asset_id_media_assets"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["video_release_id"],
            ["video_releases.id"],
            name=op.f("fk_release_presentation_revisions_video_release_id_video_releases"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_release_presentation_revisions")),
        sa.UniqueConstraint(
            "video_release_id",
            "sequence",
            name="uq_release_presentation_release_sequence",
        ),
    )
    op.create_index(
        "ix_release_presentation_release_created",
        "release_presentation_revisions",
        ["video_release_id", "created_at"],
    )

    op.create_table(
        "production_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("subject_type", sa.String(16), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("related_subject_type", sa.String(16), nullable=True),
        sa.Column("related_subject_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("source", sa.String(40), server_default="producer_ui", nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "subject_type IN ('release', 'workspace')",
            name=op.f("ck_production_events_subject_type"),
        ),
        sa.CheckConstraint(
            "length(trim(event_type)) > 0",
            name=op.f("ck_production_events_event_type_not_empty"),
        ),
        sa.CheckConstraint(
            "length(trim(source)) > 0",
            name=op.f("ck_production_events_source_not_empty"),
        ),
        sa.CheckConstraint(
            "payload_schema_version > 0",
            name=op.f("ck_production_events_payload_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "(related_subject_type IS NULL) = (related_subject_id IS NULL)",
            name=op.f("ck_production_events_related_subject_pair"),
        ),
        sa.CheckConstraint(
            "related_subject_type IS NULL OR related_subject_type IN ('release', 'workspace')",
            name=op.f("ck_production_events_related_subject_type"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_production_events")),
    )
    op.create_index(
        "ix_production_events_subject_time",
        "production_events",
        ["subject_type", "subject_id", "occurred_at"],
    )
    op.create_index(
        "ix_production_events_related_time",
        "production_events",
        ["related_subject_type", "related_subject_id", "occurred_at"],
    )
    op.create_index(
        "ix_production_events_type_time",
        "production_events",
        ["event_type", "occurred_at"],
    )
    op.execute(
        "CREATE TRIGGER trg_production_events_no_update BEFORE UPDATE ON production_events "
        "BEGIN SELECT RAISE(ABORT, 'production events are append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_production_events_no_delete BEFORE DELETE ON production_events "
        "BEGIN SELECT RAISE(ABORT, 'production events are append-only'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_release_presentation_no_update BEFORE UPDATE "
        "ON release_presentation_revisions "
        "BEGIN SELECT RAISE(ABORT, 'release presentation revisions are immutable'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_release_presentation_no_delete BEFORE DELETE "
        "ON release_presentation_revisions "
        "BEGIN SELECT RAISE(ABORT, 'release presentation revisions are immutable'); END"
    )

    bind = op.get_bind()
    releases = bind.execute(
        sa.text("SELECT id, name, status, release_date FROM video_releases ORDER BY id")
    ).mappings()
    for release in releases:
        _insert_event(
            "release",
            release["id"],
            "system.baseline_captured",
            {
                "after": {
                    "name": release["name"],
                    "status": release["status"],
                    "release_date": release["release_date"],
                }
            },
        )

    workspaces = bind.execute(
        sa.text(
            """SELECT pw.id, pw.story_external_id, pw.title, pw.status,
                      pw.video_release_id, pw.release_position,
                      vr.status AS release_status
               FROM producer_workspaces AS pw
               LEFT JOIN video_releases AS vr ON vr.id = pw.video_release_id
               ORDER BY pw.id"""
        )
    ).mappings()
    for workspace in workspaces:
        state = {
            "story_id": workspace["story_external_id"],
            "title": workspace["title"],
            "status": workspace["status"],
            "video_release_id": workspace["video_release_id"],
            "release_position": workspace["release_position"],
        }
        _insert_event(
            "workspace",
            workspace["id"],
            "system.baseline_captured",
            {"after": state},
        )
        if workspace["video_release_id"]:
            controlled_status = {
                "planned": "planned",
                "in_production": "in_production",
                "released": "completed",
            }[workspace["release_status"]]
            if workspace["status"] != controlled_status:
                bind.execute(
                    sa.text("UPDATE producer_workspaces SET status=:status WHERE id=:id"),
                    {"status": controlled_status, "id": workspace["id"]},
                )
                _insert_event(
                    "workspace",
                    workspace["id"],
                    "workspace.status_changed",
                    {
                        "before": {"status": workspace["status"]},
                        "after": {"status": controlled_status},
                    },
                    related_subject_type="release",
                    related_subject_id=workspace["video_release_id"],
                )
            relationship = {
                "baseline": True,
                "video_release_id": workspace["video_release_id"],
                "release_position": workspace["release_position"],
            }
            _insert_event(
                "workspace",
                workspace["id"],
                "workspace.release_assigned",
                {"after": relationship},
                related_subject_type="release",
                related_subject_id=workspace["video_release_id"],
            )
            _insert_event(
                "release",
                workspace["video_release_id"],
                "release.workspace_assigned",
                {"after": {**relationship, "workspace_id": workspace["id"]}},
                related_subject_type="workspace",
                related_subject_id=workspace["id"],
            )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_release_presentation_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_release_presentation_no_update")
    op.execute("DROP TRIGGER IF EXISTS trg_production_events_no_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_production_events_no_update")
    op.drop_index("ix_production_events_type_time", table_name="production_events")
    op.drop_index("ix_production_events_related_time", table_name="production_events")
    op.drop_index("ix_production_events_subject_time", table_name="production_events")
    op.drop_table("production_events")
    op.drop_index(
        "ix_release_presentation_release_created",
        table_name="release_presentation_revisions",
    )
    op.drop_table("release_presentation_revisions")
