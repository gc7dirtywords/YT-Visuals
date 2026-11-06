from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from yt_visuals.cli import cli
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.models import VideoRelease
from yt_visuals.producer.service import ProducerWorkflowError, ProducerWorkflowService
from yt_visuals.release_storage import (
    EXECUTION_CONFIRMATION,
    ReleaseStorageError,
    build_migration_plan,
    choose_storage_component,
    execute_migration,
    storage_name_base,
)


def _insert_release(
    engine, release_id: str, name: str, *, status: str = "planned", storage_path: str | None = None
) -> None:
    with Session(engine) as session:
        session.add(
            VideoRelease(
                id=release_id,
                name=name,
                status=status,
                storage_path=storage_path,
            )
        )
        session.commit()


def test_new_release_path_is_safe_unique_and_stable(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)
    first = service.create_release('ECH-R00010: Ghost / Stories?')
    assert first["storage_path"] == "ECH-R00010 - Ghost - Stories -"
    assert service.release_folder(first["id"]).name == first["storage_path"]

    second = service.create_release('ECH-R00010? Ghost \\ Stories*')
    assert second["storage_path"].endswith(f" [{second['id'][:8]}]")
    assert second["storage_path"].casefold() != first["storage_path"].casefold()

    service.rename_release(first["id"], "A completely different display title")
    renamed = service.get_release(first["id"])
    assert renamed["name"] == "A completely different display title"
    assert renamed["storage_path"] == first["storage_path"]
    assert service.release_folder(first["id"]).name == first["storage_path"]


def test_storage_name_rules_cover_windows_and_length() -> None:
    assert storage_name_base("CON") == "Release - CON"
    assert len(storage_name_base("A" * 300)) == 180
    assert storage_name_base("  ECH-R00001   -   Title. ") == "ECH-R00001 - Title"
    chosen = choose_storage_component("A:B", "12345678-0000-0000-0000-000000000000", ["A - B"])
    assert chosen == "A - B [12345678]"


def test_legacy_null_storage_uses_uuid_and_missing_or_invalid_records_fail(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)
    release = service.create_release("Legacy release")
    with Session(engine) as session:
        row = session.get(VideoRelease, release["id"])
        assert row is not None
        row.storage_path = None
        session.commit()
    assert service.release_folder(release["id"]) == catalog_settings.releases_root / release["id"]
    with pytest.raises(ProducerWorkflowError, match="not found"):
        service.release_folder("00000000-0000-0000-0000-000000000000")
    with Session(engine) as session:
        row = session.get(VideoRelease, release["id"])
        assert row is not None
        row.storage_path = "../escape"
        session.commit()
    with pytest.raises(ProducerWorkflowError, match="one directory name"):
        service.release_folder(release["id"])


def test_legacy_uuid_story_workspace_survives_restart(catalog_settings: Settings) -> None:
    from yt_visuals.producer.contracts import VisualPlan
    from tests.test_producer_workflow import _plan

    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)
    imported = service.import_plan(VisualPlan.model_validate(_plan().model_dump(mode="json")))
    release = service.create_release("Legacy UUID workspace")
    with Session(engine) as session:
        row = session.get(VideoRelease, release["id"])
        assert row is not None
        row.storage_path = None
        session.commit()
    source = catalog_settings.projects_root / imported["story_id"]
    source.mkdir(parents=True)
    source.joinpath("asset.txt").write_text("preserved", encoding="utf-8")
    service.assign_workspace_release(imported["workspace_id"], release["id"])
    expected = catalog_settings.releases_root / release["id"] / "Stories" / imported["story_id"]
    assert expected.joinpath("asset.txt").is_file()
    engine.dispose()

    restarted_engine = initialize_database(catalog_settings)
    restarted = ProducerWorkflowService(catalog_settings, restarted_engine)
    assert restarted.story_files_root(imported["workspace_id"]) == expected
    assert restarted.get_release(release["id"])["storage_path"] is None


def test_production_shaped_dry_run_reports_alias_missing_empty_and_conflict(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    ready_id = "489a27b8-4dc2-4ce5-bb80-8601623905a2"
    missing_id = "11111111-1111-1111-1111-111111111111"
    empty_id = "6621bb70-569c-49b9-a536-4cfc980fb8b3"
    conflict_id = "22222222-2222-2222-2222-222222222222"
    _insert_release(engine, ready_id, "ECH-R00010 - Ghost Stories", status="in_production")
    _insert_release(engine, missing_id, "ECH-R00001 - Archived", status="released")
    _insert_release(engine, empty_id, "ECH-R00012 - Planned")
    _insert_release(engine, conflict_id, "ECH-R00013 - Conflict")

    ready = catalog_settings.releases_root / ready_id
    ready.mkdir(parents=True)
    (ready / "story.txt").write_text("preserve", encoding="utf-8")
    empty = catalog_settings.releases_root / empty_id
    empty.mkdir()
    conflict_source = catalog_settings.releases_root / conflict_id
    conflict_source.mkdir()
    (catalog_settings.releases_root / "ECH-R00013 - Conflict").mkdir()
    alias = catalog_settings.releases_root / "ECHR00010_Ghost_R.backup-1793928910"
    try:
        alias.symlink_to(ready, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")

    entries = {entry.release_id: entry for entry in build_migration_plan(catalog_settings, engine)}
    assert entries[ready_id].state == "ready"
    assert entries[ready_id].file_count == 1
    assert entries[ready_id].backup_aliases == [
        {"path": str(alias), "target": str(ready.resolve()), "type": "symlink_alias"}
    ]
    assert entries[missing_id].state == "missing_source"
    assert "no directory will be created" in entries[missing_id].issues[0]
    assert entries[empty_id].state == "ready" and entries[empty_id].file_count == 0
    assert "empty" in entries[empty_id].issues[0]
    assert entries[conflict_id].state == "conflict"
    assert alias.is_symlink() and ready.is_dir()


def test_migration_moves_verifies_journals_and_updates_database(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    release_id = "489a27b8-4dc2-4ce5-bb80-8601623905a2"
    name = "ECH-R00010 - Ghost Stories That Became Famous Photographs"
    _insert_release(engine, release_id, name, status="in_production")
    source = catalog_settings.releases_root / release_id
    source.mkdir(parents=True)
    (source / "Stories").mkdir()
    (source / "Stories" / "asset.txt").write_text("production asset", encoding="utf-8")
    journal = catalog_settings.data_dir / "migration.jsonl"

    with pytest.raises(ReleaseStorageError, match="requires --confirm"):
        execute_migration(
            catalog_settings, engine, confirmation="", journal_path=journal,
            release_ids={release_id},
        )
    result = execute_migration(
        catalog_settings,
        engine,
        confirmation=EXECUTION_CONFIRMATION,
        journal_path=journal,
        release_ids={release_id},
    )
    destination = catalog_settings.releases_root / name
    assert not source.exists()
    assert destination.joinpath("Stories", "asset.txt").read_text(encoding="utf-8") == "production asset"
    with Session(engine) as session:
        assert session.scalar(select(VideoRelease.storage_path).where(VideoRelease.id == release_id)) == name
    assert next(entry for entry in result if entry.release_id == release_id).state == "already_migrated"
    phases = [json.loads(line)["phase"] for line in journal.read_text(encoding="utf-8").splitlines()]
    assert phases == ["planned", "moved", "committed"]


def test_migration_database_failure_restores_uuid_directory(
    catalog_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = initialize_database(catalog_settings)
    release_id = "5486808d-56cd-4f2d-bf10-a1578cd40a8a"
    name = "ECH-R00005 - Rollback"
    _insert_release(engine, release_id, name)
    source = catalog_settings.releases_root / release_id
    source.mkdir(parents=True)
    source.joinpath("asset.txt").write_text("preserve", encoding="utf-8")
    journal = catalog_settings.data_dir / "rollback.jsonl"

    def fail_commit(_session: Session) -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="database unavailable"):
        execute_migration(
            catalog_settings,
            engine,
            confirmation=EXECUTION_CONFIRMATION,
            journal_path=journal,
            release_ids={release_id},
        )
    assert source.joinpath("asset.txt").read_text(encoding="utf-8") == "preserve"
    assert not (catalog_settings.releases_root / name).exists()
    phases = [json.loads(line)["phase"] for line in journal.read_text(encoding="utf-8").splitlines()]
    assert phases == ["planned", "moved", "rolled_back"]


def test_release_storage_cli_is_read_only_by_default(
    catalog_settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    engine = initialize_database(catalog_settings)
    release_id = "90bfd15e-af10-449e-a910-ec3900aef887"
    _insert_release(engine, release_id, "ECH-R00004 - Existing")
    source = catalog_settings.releases_root / release_id
    source.mkdir(parents=True)
    (source / "asset.txt").write_text("untouched", encoding="utf-8")
    report = catalog_settings.temp_root / "report.json"
    assert cli(
        ["release-storage", "migrate", "--json", "--report", str(report)],
        settings=catalog_settings,
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "dry-run"
    assert payload["entries"][0]["state"] == "ready"
    assert json.loads(report.read_text(encoding="utf-8"))["mode"] == "dry-run"
    assert source.joinpath("asset.txt").read_text(encoding="utf-8") == "untouched"
    with Session(engine) as session:
        assert session.get(VideoRelease, release_id).storage_path is None


def test_docker_startup_never_runs_release_directory_migration() -> None:
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "docker-entrypoint.sh").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    assert "migrate_release_paths" not in entrypoint
    assert "migrate_release_paths" not in dockerfile
    assert "alembic -c /app/alembic.ini upgrade head" in entrypoint
