from __future__ import annotations

from alembic import command
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DatabaseError

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
        "production_events",
        "release_presentation_revisions",
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
        assert status.current_revision == "0011_edit_plan_guidance"

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


def test_0009_preserves_catalog_provenance_and_producer_visual_selection(
    catalog_settings: Settings,
) -> None:
    catalog_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(catalog_settings), "0008_release_metadata")
    engine = create_catalog_engine(catalog_settings)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO media_providers (id, name) VALUES (10, 'archive')"))
        connection.execute(text("""INSERT INTO media_assets
            (id, relative_path, media_type, status, sha256, usage_count)
            VALUES (20, 'Library/Images/keep.jpg', 'image', 'active', :sha, 0)"""), {"sha": "d" * 64})
        connection.execute(text("""INSERT INTO media_locations
            (id, media_asset_id, relative_path, status, provenance_type)
            VALUES (30, 20, 'Library/Images/keep.jpg', 'available', 'provider_download')"""))
        connection.execute(text("""INSERT INTO media_sources
            (id, asset_id, provider_id, provider_asset_id, source_url)
            VALUES (40, 20, 10, 'photo:keep', 'https://example.test/keep')"""))
        connection.execute(text("""INSERT INTO asset_licenses
            (id, asset_id, license_name, attribution_required)
            VALUES (50, 20, 'CC BY 4.0', 1)"""))
        connection.execute(text("INSERT INTO video_releases (id, name) VALUES ('release-keep', 'Keep Release')"))
        connection.execute(text("""INSERT INTO producer_workspaces
            (id, story_external_id, title, plan_document_sha256, plan_json, status,
             video_release_id, release_position)
            VALUES ('workspace-keep', 'story-keep', 'Keep Story', :sha, :plan,
                    'in_production', 'release-keep', 1)"""), {
            "sha": "e" * 64,
            "plan": '{"document_type":"visual_plan","contract_version":1,"story":{},"beats":[]}',
        })
        connection.execute(text("""INSERT INTO producer_beats
            (id, workspace_id, external_beat_id, sequence, specification_json,
             selected_asset_id, selected_asset_sha256)
            VALUES ('beat-keep', 'workspace-keep', 'beat-keep', 1, '{}', 20, :sha)"""), {"sha": "d" * 64})
    engine.dispose()

    command.upgrade(alembic_config(catalog_settings), "0009_sfx_catalog")
    upgraded = create_catalog_engine(catalog_settings)
    with upgraded.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM media_assets")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM media_sources")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM asset_licenses")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM media_locations")).scalar_one() == 1
        assert connection.execute(text("""SELECT selected_asset_id, selected_asset_sha256,
            selected_sfx_asset_id FROM producer_beats WHERE id='beat-keep'""")).one() == (
            20, "d" * 64, None
        )
        assert connection.execute(text("SELECT video_release_id, release_position FROM producer_workspaces")).one() == (
            "release-keep", 1
        )
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    upgraded.dispose()


def test_0010_backfills_audit_baselines_without_synthesizing_public_titles(
    catalog_settings: Settings,
) -> None:
    catalog_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(catalog_settings), "0009_sfx_catalog")
    engine = create_catalog_engine(catalog_settings)
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO video_releases (id, name, status)
                   VALUES ('release-existing', 'Internal Working Name', 'released')"""
            )
        )
        connection.execute(
            text(
                """INSERT INTO producer_workspaces
                   (id, story_external_id, title, plan_document_sha256, plan_json,
                    status, video_release_id, release_position)
                   VALUES ('workspace-existing', 'story-existing', 'Existing Story',
                           :sha, :plan, 'in_production', 'release-existing', 1)"""
            ),
            {
                "sha": "f" * 64,
                "plan": '{"document_type":"visual_plan","contract_version":1,"story":{},"beats":[]}',
            },
        )
    engine.dispose()

    command.upgrade(alembic_config(catalog_settings), "0010_release_production_memory")
    upgraded = create_catalog_engine(catalog_settings)
    with upgraded.begin() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM release_presentation_revisions")
        ).scalar_one() == 0
        assert connection.execute(
            text("SELECT status FROM producer_workspaces WHERE id='workspace-existing'")
        ).scalar_one() == "completed"
        event_types = connection.execute(
            text(
                """SELECT event_type FROM production_events
                   WHERE subject_id IN ('release-existing', 'workspace-existing')"""
            )
        ).scalars().all()
        assert event_types.count("system.baseline_captured") == 2
        assert "workspace.release_assigned" in event_types
        assert "release.workspace_assigned" in event_types
        assert "workspace.status_changed" in event_types
        with pytest.raises(DatabaseError, match="append-only"):
            connection.execute(
                text(
                    """UPDATE production_events SET source='changed'
                       WHERE subject_id='workspace-existing'"""
                )
            )
    upgraded.dispose()


def test_0011_preserves_existing_workspace_and_adds_nullable_edit_guidance(
    catalog_settings: Settings,
) -> None:
    catalog_settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(catalog_settings), "0010_release_production_memory")
    engine = create_catalog_engine(catalog_settings)
    with engine.begin() as connection:
        connection.execute(
            text(
                """INSERT INTO producer_workspaces
                   (id, story_external_id, title, plan_document_sha256, plan_json, status)
                   VALUES ('workspace-edit', 'story-edit', 'Edit Story', :sha, :plan,
                           'in_production')"""
            ),
            {"sha": "a" * 64, "plan": '{"document_type":"visual_plan"}'},
        )
        connection.execute(
            text(
                """INSERT INTO producer_beats
                   (id, workspace_id, external_beat_id, sequence, specification_json)
                   VALUES ('beat-edit', 'workspace-edit', 'beat-001', 1, :spec)"""
            ),
            {"spec": '{"desired_visual":"fireplace"}'},
        )
    engine.dispose()

    command.upgrade(alembic_config(catalog_settings), "0011_edit_plan_guidance")
    upgraded = create_catalog_engine(catalog_settings)
    with upgraded.connect() as connection:
        workspace = connection.execute(
            text(
                """SELECT story_external_id, edit_plan_document_sha256, edit_plan_json,
                          edit_plan_imported_at
                   FROM producer_workspaces WHERE id='workspace-edit'"""
            )
        ).one()
        assert workspace == ("story-edit", None, None, None)
        beat = connection.execute(
            text(
                """SELECT edit_motion_recommendation_json,
                          edit_transition_recommendation_json, producer_motion_type,
                          producer_motion_target, producer_transition_type,
                          edit_guidance_asset_sha256, edit_guidance_needs_review
                   FROM producer_beats WHERE id='beat-edit'"""
            )
        ).one()
        assert beat == (None, None, None, None, None, None, 0)
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    upgraded.dispose()
