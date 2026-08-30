"""Add shared audio catalog and beat SFX selections.

Revision ID: 0009_sfx_catalog
Revises: 0008_release_metadata
Create Date: 2026-08-29
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_sfx_catalog"
down_revision: str | None = "0008_release_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INSERT_TRIGGER = """CREATE TRIGGER trg_asset_usages_insert AFTER INSERT ON asset_usages BEGIN
UPDATE media_assets SET usage_count=(SELECT COUNT(*) FROM asset_usages WHERE asset_id=NEW.asset_id), last_used_at=(SELECT MAX(used_at) FROM asset_usages WHERE asset_id=NEW.asset_id), updated_at=CURRENT_TIMESTAMP WHERE id=NEW.asset_id; END"""
DELETE_TRIGGER = """CREATE TRIGGER trg_asset_usages_delete AFTER DELETE ON asset_usages BEGIN
UPDATE media_assets SET usage_count=(SELECT COUNT(*) FROM asset_usages WHERE asset_id=OLD.asset_id), last_used_at=(SELECT MAX(used_at) FROM asset_usages WHERE asset_id=OLD.asset_id), updated_at=CURRENT_TIMESTAMP WHERE id=OLD.asset_id; END"""
UPDATE_TRIGGER = """CREATE TRIGGER trg_asset_usages_update AFTER UPDATE OF asset_id, used_at ON asset_usages BEGIN
UPDATE media_assets SET usage_count=(SELECT COUNT(*) FROM asset_usages WHERE asset_id=OLD.asset_id), last_used_at=(SELECT MAX(used_at) FROM asset_usages WHERE asset_id=OLD.asset_id), updated_at=CURRENT_TIMESTAMP WHERE id=OLD.asset_id;
UPDATE media_assets SET usage_count=(SELECT COUNT(*) FROM asset_usages WHERE asset_id=NEW.asset_id), last_used_at=(SELECT MAX(used_at) FROM asset_usages WHERE asset_id=NEW.asset_id), updated_at=CURRENT_TIMESTAMP WHERE id=NEW.asset_id; END"""


def _drop_usage_triggers() -> None:
    for name in ("trg_asset_usages_update", "trg_asset_usages_delete", "trg_asset_usages_insert"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")


def _create_usage_triggers() -> None:
    op.execute(INSERT_TRIGGER)
    op.execute(DELETE_TRIGGER)
    op.execute(UPDATE_TRIGGER)


def _foreign_keys(enabled: bool) -> None:
    # SQLite cannot replace a CHECK constraint in place. Alembic's batch copy is
    # safe only while child FKs are disabled on this one migration connection.
    # The migration finishes by re-enabling and checking every relationship.
    with op.get_context().autocommit_block():
        op.get_bind().exec_driver_sql(
            f"PRAGMA foreign_keys={'ON' if enabled else 'OFF'}"
        )


def upgrade() -> None:
    _foreign_keys(False)
    _drop_usage_triggers()
    with op.batch_alter_table("media_assets", recreate="always") as batch:
        batch.add_column(sa.Column("sfx_kind", sa.String(16), nullable=True))
        batch.drop_constraint(op.f("ck_media_assets_media_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_media_assets_media_type"),
            "media_type IN ('image', 'video', 'audio')",
        )
        batch.create_check_constraint(
            op.f("ck_media_assets_sfx_kind"),
            "sfx_kind IS NULL OR sfx_kind IN ('one_shot', 'ambient')",
        )
    with op.batch_alter_table("media_downloads", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_media_downloads_media_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_media_downloads_media_type"),
            "media_type IN ('image', 'video', 'audio')",
        )
    _create_usage_triggers()
    # SQLite supports a nullable REFERENCES column directly even though Alembic's
    # generic add_column implementation attempts a second unsupported FK ALTER.
    op.execute(
        "ALTER TABLE producer_beats ADD COLUMN selected_sfx_asset_id INTEGER "
        "REFERENCES media_assets(id) ON DELETE RESTRICT"
    )
    op.add_column(
        "producer_beats",
        sa.Column("selected_sfx_asset_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "producer_beats",
        sa.Column("selected_sfx_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_producer_beats_selected_sfx_asset_id",
        "producer_beats",
        ["selected_sfx_asset_id"],
    )
    _foreign_keys(True)
    failures = op.get_bind().exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    if failures:
        raise RuntimeError(f"foreign key check failed after 0009 migration: {failures[:5]}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM media_assets WHERE media_type='audio')"
    ).scalar():
        raise RuntimeError("remove audio catalog records before downgrading from 0009")
    if bind.exec_driver_sql(
        "SELECT EXISTS(SELECT 1 FROM media_downloads WHERE media_type='audio')"
    ).scalar():
        raise RuntimeError("remove audio acquisition history before downgrading from 0009")
    _foreign_keys(False)
    op.drop_index("ix_producer_beats_selected_sfx_asset_id", table_name="producer_beats")
    with op.batch_alter_table("producer_beats", recreate="always") as batch:
        batch.drop_column("selected_sfx_at")
        batch.drop_column("selected_sfx_asset_sha256")
        batch.drop_column("selected_sfx_asset_id")
    _drop_usage_triggers()
    with op.batch_alter_table("media_downloads", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_media_downloads_media_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_media_downloads_media_type"), "media_type IN ('image', 'video')"
        )
    with op.batch_alter_table("media_assets", recreate="always") as batch:
        batch.drop_constraint(op.f("ck_media_assets_sfx_kind"), type_="check")
        batch.drop_constraint(op.f("ck_media_assets_media_type"), type_="check")
        batch.create_check_constraint(
            op.f("ck_media_assets_media_type"), "media_type IN ('image', 'video')"
        )
        batch.drop_column("sfx_kind")
    _create_usage_triggers()
    _foreign_keys(True)
