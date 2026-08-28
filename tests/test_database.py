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
        "video_releases",
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
        assert status.current_revision == "0008_release_metadata"

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


def test_0007_preserves_workspace_ids_and_producer_beats(
    catalog_settings: Settings,
) -> None:
    catalog_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(catalog_settings), "0006_producer_workspaces")
    engine = create_catalog_engine(catalog_settings)
    plan_json = '{"document_type":"visual_plan","contract_version":1,"story":{},"beats":[]}'
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO producer_workspaces
                (id, story_external_id, title, plan_document_sha256, plan_json, status)
                VALUES (:id, :story_id, :title, :sha, :plan, :status)"""
            ),
            [
                {"id": "workspace-10", "story_id": "story-a", "title": "Story A", "sha": "a" * 64, "plan": plan_json, "status": "active"},
                {"id": "workspace-20", "story_id": "story-b", "title": "Story B", "sha": "b" * 64, "plan": plan_json, "status": "complete"},
            ],
        )
        connection.execute(
            text(
                """INSERT INTO producer_beats
                (id, workspace_id, external_beat_id, sequence, specification_json)
                VALUES (:id, :workspace_id, :beat_id, :sequence, :spec)"""
            ),
            [
                {"id": "beat-a1", "workspace_id": "workspace-10", "beat_id": "a-1", "sequence": 1, "spec": "{}"},
                {"id": "beat-a2", "workspace_id": "workspace-10", "beat_id": "a-2", "sequence": 2, "spec": "{}"},
                {"id": "beat-b1", "workspace_id": "workspace-20", "beat_id": "b-1", "sequence": 1, "spec": "{}"},
            ],
        )
    engine.dispose()

    command.upgrade(alembic_config(catalog_settings), "0007_workspace_organization")
    upgraded = create_catalog_engine(catalog_settings)
    with upgraded.connect() as connection:
        workspaces = connection.execute(
            text("SELECT id, status, video_release_id, release_position FROM producer_workspaces ORDER BY id")
        ).all()
        beats = connection.execute(
            text("SELECT id, workspace_id FROM producer_beats ORDER BY id")
        ).all()
        assert workspaces == [
            ("workspace-10", "in_production", None, None),
            ("workspace-20", "completed", None, None),
        ]
        assert beats == [
            ("beat-a1", "workspace-10"),
            ("beat-a2", "workspace-10"),
            ("beat-b1", "workspace-20"),
        ]
        assert connection.execute(text("SELECT count(*) FROM producer_workspaces")).scalar_one() == 2
    upgraded.dispose()


def test_0008_adds_release_metadata_without_touching_producer_rows(
    catalog_settings: Settings,
) -> None:
    catalog_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(catalog_settings), "0007_workspace_organization")
    engine = create_catalog_engine(catalog_settings)
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO producer_workspaces
            (id, story_external_id, title, plan_document_sha256, plan_json, status)
            VALUES ('workspace-keep', 'story-keep', 'Keep Story', :sha, :plan, 'in_production')"""),
            {"sha": "c" * 64, "plan": '{"document_type":"visual_plan","contract_version":1,"story":{},"beats":[]}'},
        )
        connection.execute(
            text("""INSERT INTO producer_beats
            (id, workspace_id, external_beat_id, sequence, specification_json)
            VALUES ('beat-keep', 'workspace-keep', 'beat-keep', 1, '{}')""")
        )
        connection.execute(text("INSERT INTO video_releases (id, name) VALUES ('release-keep', 'Keep Release')"))
    engine.dispose()

    command.upgrade(alembic_config(catalog_settings), "0008_release_metadata")
    upgraded = create_catalog_engine(catalog_settings)
    with upgraded.connect() as connection:
        assert connection.execute(text("SELECT status, release_date FROM video_releases")).one() == ("planned", None)
        assert connection.execute(text("SELECT id, workspace_id FROM producer_beats")).one() == ("beat-keep", "workspace-keep")
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    upgraded.dispose()
