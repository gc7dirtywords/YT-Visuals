from __future__ import annotations

import io
from pathlib import Path

from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.producer.service import ProducerWorkflowService
from yt_visuals.producer.web import create_app


def test_configured_container_roots_and_health(monkeypatch, tmp_path: Path) -> None:
    for name, value in {
        "YT_CHANNELOPS_CONFIG_ROOT": tmp_path / "config",
        "YT_CHANNELOPS_PROJECTS_ROOT": tmp_path / "projects",
        "YT_CHANNELOPS_LIBRARY_ROOT": tmp_path / "library",
        "YT_CHANNELOPS_RELEASES_ROOT": tmp_path / "releases",
        "YT_CHANNELOPS_TEMP_ROOT": tmp_path / "temp",
        "YT_CHANNELOPS_SERVER_MODE": "1",
    }.items():
        monkeypatch.setenv(name, str(value))
    settings = Settings(root=Path(__file__).resolve().parents[1])
    assert settings.data_dir == tmp_path / "config"
    assert settings.projects_root == tmp_path / "projects"
    assert settings.library_root == tmp_path / "library"
    assert settings.releases_root == tmp_path / "releases"
    assert settings.temp_root == tmp_path / "temp"
    assert settings.server_mode is True
    engine = initialize_database(settings)
    app = create_app(settings, engine=engine)
    response = app.test_client().get("/health")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    engine.dispose()


def test_release_artifact_upload_download_and_persistence(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)
    release = service.create_release("Deployment Artifact Release")
    app = create_app(catalog_settings, engine=engine, service=service)
    app.config.update(TESTING=True)
    client = app.test_client()
    uploaded = client.post(
        f"/releases/{release['id']}/artifacts",
        data={"artifact_type": "resolve_project", "artifact_file": (io.BytesIO(b'PK\x03\x04artifact'), "timeline.zip")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    assert b"Release artifact stored as version 1" in uploaded.data
    detail = service.get_release(release["id"])
    artifact = next(group["current"] for group in detail["artifacts"] if group["artifact_type"] == "resolve_project")
    assert (catalog_settings.root / "Releases" / release["id"] / artifact["stored_filename"]).is_file()
    downloaded = client.get(f"/releases/{release['id']}/artifacts/{artifact['id']}/download")
    assert downloaded.status_code == 200 and downloaded.data == b"PK\x03\x04artifact"
    engine.dispose()
    restarted = ProducerWorkflowService(catalog_settings, initialize_database(catalog_settings))
    assert next(group["current"] for group in restarted.get_release(release["id"])["artifacts"] if group["artifact_type"] == "resolve_project")["sha256"] == artifact["sha256"]
