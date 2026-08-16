from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection

from .config import Settings


@dataclass(frozen=True, slots=True)
class MigrationStatus:
    current_revision: str | None
    head_revision: str

    @property
    def is_current(self) -> bool:
        return self.current_revision == self.head_revision


def _enable_sqlite_foreign_keys(dbapi_connection: sqlite3.Connection, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_catalog_engine(settings: Settings) -> Engine:
    engine = create_engine(settings.database_url, future=True)
    event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def alembic_config(settings: Settings) -> Config:
    config = Config(str(settings.alembic_ini))
    config.set_main_option("script_location", str(settings.migrations_dir))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def run_migrations(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(settings), "head")


def get_migration_status(settings: Settings, connection: Connection) -> MigrationStatus:
    context = MigrationContext.configure(connection)
    current = context.get_current_revision()
    script = ScriptDirectory.from_config(alembic_config(settings))
    head = script.get_current_head()
    if head is None:
        raise RuntimeError("No migration head is defined")
    return MigrationStatus(current_revision=current, head_revision=head)


def initialize_database(settings: Settings) -> Engine:
    run_migrations(settings)
    engine = create_catalog_engine(settings)
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        status = get_migration_status(settings, connection)
        if not status.is_current:
            raise RuntimeError(
                f"Database migration mismatch: current={status.current_revision}, head={status.head_revision}"
            )
    return engine
