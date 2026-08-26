from __future__ import annotations

from alembic import command
from sqlalchemy import inspect, text

from yt_visuals.config import Settings
from yt_visuals.database import (
    alembic_config,
    create_catalog_engine,
    get_migration_status,
    initialize_database,
)


def test_database_is_created_and_migrated(catalog_settings: Settings) -> None:
    assert not catalog_settings.database_path.exists()

    engine = initialize_database(catalog_settings)
    assert catalog_settings.database_path.is_file()

    expected_tables = {
        "alembic_version",
        "asset_licenses",
        "asset_tags",
        "asset_usages",
        "asset_review_annotations",
        "beat_asset_rejections",
        "beat_candidates",
        "beat_selections",
        "candidate_packages",
        "media_assets",
        "media_downloads",
        "media_locations",
        "media_providers",
        "media_sources",
        "projects",
        "producer_beat_hidden_assets",
        "producer_beats",
        "producer_workspaces",
        "stories",
        "tags",
        "visual_beat_revisions",
        "visual_beats",
        "visual_request_revisions",
        "visual_review_entries",
        "visual_review_templates",
        "visual_reviews",
        "visual_workflows",
    }
    assert expected_tables == set(inspect(engine).get_table_names())

    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        status = get_migration_status(catalog_settings, connection)
        assert status.is_current
        assert status.current_revision == "0006_producer_workspaces"

    engine.dispose()


def test_database_initialization_is_idempotent(catalog_settings: Settings) -> None:
    first_engine = initialize_database(catalog_settings)
    first_engine.dispose()
    second_engine = initialize_database(catalog_settings)
    second_engine.dispose()


def test_upgrade_from_0005_adds_only_producer_tables(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    engine.dispose()
    command.downgrade(alembic_config(catalog_settings), "0005_visual_workflow")
    downgraded = create_catalog_engine(catalog_settings)
    assert "producer_workspaces" not in inspect(downgraded).get_table_names()
    downgraded.dispose()
    command.upgrade(alembic_config(catalog_settings), "head")
    upgraded = initialize_database(catalog_settings)
    assert {
        "producer_workspaces", "producer_beats", "producer_beat_hidden_assets"
    } <= set(inspect(upgraded).get_table_names())
    upgraded.dispose()
