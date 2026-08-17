"""Add usage service context and idempotency support.

Revision ID: 0004_usage_context
Revises: 0003_local_locations
Create Date: 2026-08-16
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_usage_context"
down_revision: str | None = "0003_local_locations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INSERT_TRIGGER = """
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

DELETE_TRIGGER = """
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

UPDATE_TRIGGER = """
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


def _drop_usage_triggers() -> None:
    for name in ("trg_asset_usages_update", "trg_asset_usages_delete", "trg_asset_usages_insert"):
        op.execute(f"DROP TRIGGER IF EXISTS {name}")


def _create_usage_triggers() -> None:
    op.execute(INSERT_TRIGGER)
    op.execute(DELETE_TRIGGER)
    op.execute(UPDATE_TRIGGER)


def upgrade() -> None:
    _drop_usage_triggers()
    with op.batch_alter_table("asset_usages") as batch:
        batch.add_column(sa.Column("project_id", sa.Integer()))
        batch.add_column(sa.Column("usage_reference", sa.String(255)))
        batch.add_column(sa.Column("idempotency_key", sa.String(255)))
        batch.alter_column("story_id", existing_type=sa.Integer(), nullable=True)
        batch.create_foreign_key(
            op.f("fk_asset_usages_project_id_projects"),
            "projects",
            ["project_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_unique_constraint(
            op.f("uq_asset_usages_idempotency_key"), ["idempotency_key"]
        )
    op.execute(
        "UPDATE asset_usages SET project_id = "
        "(SELECT project_id FROM stories WHERE stories.id = asset_usages.story_id)"
    )
    op.create_index(
        "ix_asset_usages_project_used", "asset_usages", ["project_id", "used_at"]
    )
    _create_usage_triggers()


def downgrade() -> None:
    _drop_usage_triggers()
    op.drop_index("ix_asset_usages_project_used", table_name="asset_usages")
    op.execute("DELETE FROM asset_usages WHERE story_id IS NULL")
    with op.batch_alter_table("asset_usages") as batch:
        batch.drop_constraint(op.f("uq_asset_usages_idempotency_key"), type_="unique")
        batch.drop_constraint(op.f("fk_asset_usages_project_id_projects"), type_="foreignkey")
        batch.alter_column("story_id", existing_type=sa.Integer(), nullable=False)
        batch.drop_column("idempotency_key")
        batch.drop_column("usage_reference")
        batch.drop_column("project_id")
    _create_usage_triggers()
