from __future__ import annotations

from sqlalchemy import inspect, text

from yt_visuals.config import Settings
from yt_visuals.database import get_migration_status, initialize_database


def test_database_is_created_and_migrated(catalog_settings: Settings) -> None:
    assert not catalog_settings.database_path.exists()

    engine = initialize_database(catalog_settings)
    assert catalog_settings.database_path.is_file()

    expected_tables = {
        "alembic_version",
        "asset_licenses",
        "asset_tags",
        "asset_usages",
        "media_assets",
        "media_providers",
        "media_sources",
        "projects",
        "stories",
        "tags",
    }
    assert expected_tables == set(inspect(engine).get_table_names())

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        status = get_migration_status(catalog_settings, connection)
        assert status.is_current
        assert status.current_revision == "0001_initial"

    engine.dispose()


def test_database_initialization_is_idempotent(catalog_settings: Settings) -> None:
    first_engine = initialize_database(catalog_settings)
    first_engine.dispose()
    second_engine = initialize_database(catalog_settings)
    second_engine.dispose()

