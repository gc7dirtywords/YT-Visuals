from __future__ import annotations

import csv
import hashlib
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from yt_visuals.acquisition import AcquisitionService
from yt_visuals.config import Settings
from yt_visuals.credentials import CredentialStore, PEXELS_CREDENTIAL_NAME, SERVICE_NAME
from yt_visuals.database import initialize_database
from yt_visuals.library import LibraryScanner
from yt_visuals.models import MediaAsset, MediaDownload, MediaLocation, MediaSource, ProducerBeat, ProductionEvent
from yt_visuals.providers.errors import ProviderAuthenticationError, ProviderConnectionError
from yt_visuals.producer.web import create_app
from yt_visuals.producer.service import (
    ProducerWorkflowError,
    ProducerWorkflowService,
    WIKIMEDIA_USER_AGENT,
    resolve_wikimedia_file_page,
)


class FakeKeyring:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def get_password(self, service: str, username: str) -> str | None:
        assert (service, username) == (SERVICE_NAME, PEXELS_CREDENTIAL_NAME)
        return self.value

    def set_password(self, service: str, username: str, password: str) -> None:
        assert (service, username) == (SERVICE_NAME, PEXELS_CREDENTIAL_NAME)
        self.value = password

    def delete_password(self, service: str, username: str) -> None:
        assert (service, username) == (SERVICE_NAME, PEXELS_CREDENTIAL_NAME)
        self.value = None


def _plan_bytes() -> bytes:
    return b'''{
      "document_type":"visual_plan","contract_version":1,
      "story":{"story_id":"web-story","title":"Web Story"},
      "beats":[{"beat_id":"beat-001","sequence":1,
        "narration_context":"A door slams.","desired_visual":"A closed old door",
        "search_queries":["closed old door"],"must_have":[],"avoid":[],
        "media_preference":"image","source_requirement":"representative",
        "production_opportunities":[]}]
    }'''


def _edit_plan_bytes() -> bytes:
    return b'''{
      "document_type":"edit_plan","contract_version":1,
      "story":{"story_id":"web-story"},
      "beats":[{"beat_id":"beat-001","sequence":1,
        "motion_recommendation":{"type":"slow_zoom_in","purpose":"Focus on the door.","target":"door handle"},
        "transition_out_recommendation":null}]
    }'''


def _jpeg() -> io.BytesIO:
    stream = io.BytesIO()
    Image.new("RGB", (120, 68), "brown").save(stream, format="JPEG")
    stream.seek(0)
    return stream


def test_selected_sfx_uses_native_audio_controls_without_autoplay(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    service = ProducerWorkflowService(catalog_settings, engine)
    from yt_visuals.producer.contracts import VisualPlan

    imported = service.import_plan(VisualPlan.model_validate_json(_plan_bytes()))
    beat = service.get_workspace(imported["workspace_id"], include_candidates=False)["beats"][0]
    path = catalog_settings.root / "Library/SFX/preview.wav"
    path.write_bytes(b"preview bytes")
    with Session(engine) as session:
        asset = MediaAsset(
            relative_path="Library/SFX/preview.wav", media_type="audio",
            sfx_kind="one_shot", status="active", title="Preview hit",
            mime_type="audio/wav", file_size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), duration_ms=800,
        )
        session.add(asset)
        session.flush()
        session.add(MediaLocation(
            asset=asset, relative_path=asset.relative_path, status="available",
            provenance_type="local_import", file_size_bytes=path.stat().st_size,
        ))
        session.commit()
        asset_id = asset.id
    service.select_sfx(imported["workspace_id"], beat["id"], asset_id)

    app = create_app(catalog_settings, engine=engine, service=service)
    app.config.update(TESTING=True)
    response = app.test_client().get(f"/stories/{imported['workspace_id']}")
    assert response.status_code == 200
    assert b"<audio" in response.data and b"controls" in response.data
    assert b"autoplay" not in response.data
    engine.dispose()


def test_web_plan_import_workspace_and_upload_selection(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    app = create_app(catalog_settings, engine=engine)
    app.config.update(TESTING=True)
    client = app.test_client()
    response = client.post(
        "/plans",
        data={"visual_plan": (io.BytesIO(_plan_bytes()), "plan.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Web Story" in response.data
    assert b"Recommended searches" in response.data
    service = app.extensions["producer_service"]
    workspace = service.list_workspaces()[0]
    detail = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    beat = detail["beats"][0]
    uploaded = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/upload",
        data={"media_file": (_jpeg(), "chosen-door.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    assert b"Uploaded media validated" in uploaded.data
    assert b"Current selection" in uploaded.data
    assert b"License: UNKNOWN" in uploaded.data
    assert b'class="selected" data-beat-link="beat-001"' in uploaded.data
    assert client.get("/static/producer.css").status_code == 200
    engine.dispose()


def test_web_plan_import_accepts_direct_json_paste(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    app = create_app(catalog_settings, engine=engine)
    app.config.update(TESTING=True)
    response = app.test_client().post(
        "/plans",
        data={"visual_plan_json": _plan_bytes().decode("utf-8")},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Web Story" in response.data
    assert b"Visual Plan imported" in response.data
    assert len(app.extensions["producer_service"].list_workspaces()) == 1
    engine.dispose()


def test_web_edit_plan_import_by_paste_and_file_with_compact_guidance(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    selected = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/upload",
        data={"media_file": (_jpeg(), "door.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert selected.status_code == 200
    pasted = client.post(
        f"/stories/{workspace['workspace_id']}/edit-plan",
        data={"edit_plan_json": _edit_plan_bytes().decode("utf-8")},
        follow_redirects=True,
    )
    assert pasted.status_code == 200
    assert b"Edit Plan imported for 1 beats" in pasted.data
    assert b"Project recommendation" in pasted.data
    assert b"Producer choice" in pasted.data
    assert b"Slow Zoom In" in pasted.data

    updated = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/edit-guidance",
        data={"motion_type": "pan_left", "motion_target": "door", "transition_type": ""},
        follow_redirects=True,
    )
    assert b"Producer edit guidance updated" in updated.data
    assert b"Pan Left" in updated.data
    reset = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/edit-guidance/reset",
        follow_redirects=True,
    )
    assert b"reset to the Project recommendation" in reset.data

    uploaded = client.post(
        f"/stories/{workspace['workspace_id']}/edit-plan",
        data={"edit_plan": (io.BytesIO(_edit_plan_bytes()), "edit-plan.json")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    assert b"Edit Plan imported for 1 beats" in uploaded.data
    assert service.get_workspace(workspace["workspace_id"], include_candidates=False)["edit_plan"]["imported"]
    engine.dispose()


def test_web_story_document_upload_history_view_and_download(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, workspace, _beat = _workspace_client(catalog_settings)
    workspace_id = workspace["workspace_id"]
    initial = client.get(f"/stories/{workspace_id}")
    assert b"Story Documents" in initial.data
    assert b"Narration Script" in initial.data
    assert b"Narrator Copy" in initial.data
    assert b"Subtitles" in initial.data

    first_content = b"First subtitle document\n"
    first = client.post(
        f"/stories/{workspace_id}/documents",
        data={
            "document_type": "subtitles",
            "story_document": (io.BytesIO(first_content), "subtitles-original.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert first.status_code == 200
    assert b"Subtitles version 1 stored" in first.data
    assert b"subtitles-original.txt" in first.data

    second_content = b"Revised subtitle document\n"
    second = client.post(
        f"/stories/{workspace_id}/documents",
        data={
            "document_type": "subtitles",
            "story_document": (io.BytesIO(second_content), "subtitles-revised.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Subtitles version 2 stored" in second.data
    assert "Current · v2".encode("utf-8") in second.data
    assert b"Earlier versions (1)" in second.data

    documents = service.get_workspace(workspace_id, include_candidates=False)["documents"]
    subtitles = next(item for item in documents if item["document_type"] == "subtitles")
    current = subtitles["current"]
    earlier = subtitles["versions"][1]
    viewed = client.get(
        f"/stories/{workspace_id}/documents/{earlier['id']}/view"
    )
    assert viewed.status_code == 200 and viewed.data == first_content
    assert "inline" in viewed.headers["Content-Disposition"]
    downloaded = client.get(
        f"/stories/{workspace_id}/documents/{current['id']}/download"
    )
    assert downloaded.status_code == 200 and downloaded.data == second_content
    assert "attachment" in downloaded.headers["Content-Disposition"]
    assert "subtitles-revised.txt" in downloaded.headers["Content-Disposition"]

    rejected = client.post(
        f"/stories/{workspace_id}/documents",
        data={
            "document_type": "narrator_copy",
            "story_document": (io.BytesIO(b"not pdf"), "copy.txt"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Narrator Copy accepts only" in rejected.data
    engine.dispose()


def test_integration_settings_never_render_saved_key(catalog_settings: Settings, monkeypatch) -> None:
    monkeypatch.delenv(PEXELS_CREDENTIAL_NAME, raising=False)
    engine = initialize_database(catalog_settings)
    secret = "saved-key-that-must-not-render"
    app = create_app(
        catalog_settings,
        engine=engine,
        credential_store=CredentialStore(FakeKeyring(secret)),
    )
    app.config.update(TESTING=True)

    response = app.test_client().get("/settings/integrations")

    assert response.status_code == 200
    assert b"Configured" in response.data
    assert b"Windows Credential Manager" in response.data
    assert secret.encode() not in response.data
    assert b'value="' not in response.data
    engine.dispose()


def test_missing_credential_banner_links_to_settings(catalog_settings: Settings, monkeypatch) -> None:
    monkeypatch.delenv(PEXELS_CREDENTIAL_NAME, raising=False)
    engine = initialize_database(catalog_settings)
    app = create_app(
        catalog_settings,
        engine=engine,
        credential_store=CredentialStore(FakeKeyring()),
    )
    app.config.update(TESTING=True)

    response = app.test_client().get("/")

    assert b"/settings/integrations" in response.data
    engine.dispose()


def test_save_and_test_connection_use_only_submitted_secret(
    catalog_settings: Settings, monkeypatch
) -> None:
    monkeypatch.delenv(PEXELS_CREDENTIAL_NAME, raising=False)
    engine = initialize_database(catalog_settings)
    backend = FakeKeyring()
    tested: list[str] = []
    app = create_app(
        catalog_settings,
        engine=engine,
        credential_store=CredentialStore(backend),
        pexels_tester=tested.append,
    )
    app.config.update(TESTING=True)
    client = app.test_client()
    secret = "submitted-secret-that-must-not-render"

    saved = client.post(
        "/settings/integrations/pexels/save",
        data={"api_key": secret},
        follow_redirects=True,
    )
    tested_response = client.post(
        "/settings/integrations/pexels/test",
        data={"api_key": secret},
        follow_redirects=True,
    )

    assert backend.value == secret
    assert tested == [secret]
    assert b"saved" in saved.data
    assert b"connection succeeded" in tested_response.data
    assert secret.encode() not in saved.data + tested_response.data
    engine.dispose()


def test_connection_errors_distinguish_authentication_from_network(
    catalog_settings: Settings, monkeypatch
) -> None:
    monkeypatch.delenv(PEXELS_CREDENTIAL_NAME, raising=False)
    engine = initialize_database(catalog_settings)
    backend = FakeKeyring("stored-secret")

    def rejected(_: str) -> None:
        raise ProviderAuthenticationError("provider details")

    auth_app = create_app(
        catalog_settings,
        engine=engine,
        credential_store=CredentialStore(backend),
        pexels_tester=rejected,
    )
    auth_app.config.update(TESTING=True)
    auth = auth_app.test_client().post(
        "/settings/integrations/pexels/test", data={}, follow_redirects=True
    )
    assert b"rejected the API key" in auth.data

    def unavailable(_: str) -> None:
        raise ProviderConnectionError("network unavailable")

    network_app = create_app(
        catalog_settings,
        engine=engine,
        credential_store=CredentialStore(backend),
        pexels_tester=unavailable,
    )
    network_app.config.update(TESTING=True)
    network = network_app.test_client().post(
        "/settings/integrations/pexels/test", data={}, follow_redirects=True
    )
    assert b"could not be reached" in network.data
    assert b"network unavailable" in network.data
    engine.dispose()


def test_remove_only_keyring_and_reports_environment_override(
    catalog_settings: Settings, monkeypatch
) -> None:
    monkeypatch.setenv(PEXELS_CREDENTIAL_NAME, "environment-secret")
    engine = initialize_database(catalog_settings)
    backend = FakeKeyring("stored-secret")
    app = create_app(
        catalog_settings,
        engine=engine,
        credential_store=CredentialStore(backend),
    )
    app.config.update(TESTING=True)

    response = app.test_client().post(
        "/settings/integrations/pexels/remove", follow_redirects=True
    )

    assert backend.value is None
    assert b"remains configured through the environment override" in response.data
    assert b"environment-secret" not in response.data
    engine.dispose()


def _workspace_client(catalog_settings: Settings, **app_kwargs):
    engine = initialize_database(catalog_settings)
    app = create_app(catalog_settings, engine=engine, **app_kwargs)
    app.config.update(TESTING=True)
    client = app.test_client()
    client.post(
        "/plans",
        data={"visual_plan": (io.BytesIO(_plan_bytes()), "plan.json")},
        content_type="multipart/form-data",
    )
    service = app.extensions["producer_service"]
    workspace = service.list_workspaces()[0]
    beat = service.get_workspace(
        workspace["workspace_id"], include_candidates=False
    )["beats"][0]
    return engine, app, client, service, workspace, beat


def test_beat_actions_redirect_to_stable_anchor(catalog_settings: Settings, monkeypatch) -> None:
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    workspace_id = workspace["workspace_id"]
    beat_id = beat["id"]
    monkeypatch.setattr(service, "select_asset", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "clear_selection", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "hide_asset", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "restore_asset", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "import_pexels_page", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "import_external_media", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "import_upload", lambda *args, **kwargs: None)

    requests = [
        (f"/stories/{workspace_id}/beats/{beat_id}/select/91", {}),
        (f"/stories/{workspace_id}/beats/{beat_id}/clear", {}),
        (f"/stories/{workspace_id}/beats/{beat_id}/hide/91", {}),
        (f"/stories/{workspace_id}/beats/{beat_id}/restore/91", {}),
        (f"/stories/{workspace_id}/beats/{beat_id}/pexels", {"source_url": "x"}),
        (
            f"/stories/{workspace_id}/beats/{beat_id}/external",
            {"direct_media_url": "x"},
        ),
    ]
    for path, data in requests:
        response = client.post(path, data=data)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("#beat-001")
        assert "focus=beat-001" in response.headers["Location"]

    upload = client.post(
        f"/stories/{workspace_id}/beats/{beat_id}/upload",
        data={"media_file": (_jpeg(), "chosen.jpg")},
        content_type="multipart/form-data",
    )
    assert upload.headers["Location"].endswith("#beat-001")
    assert "panel=local" in upload.headers["Location"]

    def fail_external(*args, **kwargs):
        raise ProducerWorkflowError("unsupported external media")

    monkeypatch.setattr(service, "import_external_media", fail_external)
    failed = client.post(
        f"/stories/{workspace_id}/beats/{beat_id}/external",
        data={"direct_media_url": "https://example.test/page.html"},
    )
    assert failed.headers["Location"].endswith("#beat-001")
    assert "panel=external" in failed.headers["Location"]
    engine.dispose()


def test_workspace_renders_sticky_progress_navigation_and_external_import(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, _service, workspace, _beat = _workspace_client(catalog_settings)

    response = client.get(f"/stories/{workspace['workspace_id']}")

    assert b'class="production-toolbar"' in response.data
    assert b'class="toolbar-progress"><b>0 / 1</b> SELECTED' in response.data
    assert b"Storyboard pending" in response.data
    assert b'class="beat-navigator"' in response.data
    assert b'href="#beat-001"' in response.data
    assert b'class="unselected" data-beat-link="beat-001"' in response.data
    assert b'id="beat-001" data-beat-card' in response.data
    assert b"External / Other Source" in response.data
    assert b"Local Library / Upload" in response.data
    assert b"<summary>Pexels</summary>" in response.data
    assert b'<details class="sourcing-panel local" >' in response.data
    assert b'<details class="sourcing-panel pexels" >' in response.data
    assert b'<details class="sourcing-panel external" >' in response.data
    assert b'name="direct_media_url"' in response.data
    assert b'name="source_page_url"' in response.data
    assert b"IntersectionObserver" in client.get("/static/producer.js").data
    assert b'class="production-column"' in response.data
    assert b"Organization" in response.data
    assert b"Open Edit Folder" in response.data
    assert b"Copy Path" in response.data
    engine.dispose()


def test_rendered_external_form_drives_full_wikimedia_import_and_persistence(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    file_page = "https://commons.wikimedia.org/wiki/File:Rendered_form.jpg"
    direct_url = "https://upload.wikimedia.org/wikipedia/commons/a/a1/Rendered_form.jpg"
    media_bytes = _jpeg().read()
    requests: list[tuple[str, str]] = []

    def external_http(request: httpx.Request) -> httpx.Response:
        requests.append((request.url.host, request.url.path))
        if request.url.host == "commons.wikimedia.org":
            assert request.headers["User-Agent"] == WIKIMEDIA_USER_AGENT
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "imageinfo": [
                                    {
                                        "url": direct_url,
                                        "descriptionurl": file_page,
                                        "extmetadata": {
                                            "Artist": {"value": "<b>Archive Author</b>"},
                                            "LicenseShortName": {"value": "CC0 1.0"},
                                            "LicenseUrl": {
                                                "value": "https://creativecommons.org/publicdomain/zero/1.0/"
                                            },
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
        if request.url.host == "upload.wikimedia.org":
            return httpx.Response(
                200, headers={"Content-Type": "image/jpeg"}, content=media_bytes
            )
        raise AssertionError(f"unexpected external request host: {request.url.host}")

    boundary_client = httpx.Client(
        transport=httpx.MockTransport(external_http),
        follow_redirects=True,
        headers={"User-Agent": WIKIMEDIA_USER_AGENT},
    )
    service.wikimedia_resolver = lambda page: resolve_wikimedia_file_page(
        page, http_client=boundary_client
    )
    service.acquisition_factory = lambda settings, supplied: AcquisitionService(
        settings, supplied, http_client=boundary_client
    )

    rendered = client.get(f"/stories/{workspace['workspace_id']}")
    form_match = re.search(
        rb'<form action="([^"]+/external)" method="([^"]+)">(.*?)</form>',
        rendered.data,
        re.DOTALL,
    )
    assert form_match is not None
    action = form_match.group(1).decode()
    assert form_match.group(2) == b"post"
    rendered_names = {
        name.decode()
        for name in re.findall(rb'name="([^"]+)"', form_match.group(3))
    }
    assert rendered_names == {
        "direct_media_url",
        "source_page_url",
        "creator_attribution",
        "license_name",
        "license_url",
    }

    form_data = {name: "" for name in rendered_names}
    form_data["direct_media_url"] = file_page
    posted = client.post(action, data=form_data)
    assert posted.status_code == 302
    assert "panel=external" in posted.headers["Location"]

    detail = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    selected = detail["beats"][0]["selected"]
    assert selected is not None, client.get(posted.headers["Location"]).data.decode()
    assert selected["source"]["source_url"] == file_page
    assert selected["source"]["creator_name"] == "Archive Author"
    assert selected["license"]["name"] == "CC0 1.0"
    assert client.get(f"/media/{selected['asset_id']}").status_code == 200
    refreshed = client.get(posted.headers["Location"])
    assert b"Current selection" in refreshed.data
    assert b"Archive Author" in refreshed.data
    restarted_service = ProducerWorkflowService(catalog_settings, engine)
    restarted = restarted_service.get_workspace(
        workspace["workspace_id"], include_candidates=False
    )
    assert restarted["beats"][0]["selected"]["asset_id"] == selected["asset_id"]

    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        assert session.scalar(select(func.count()).select_from(MediaSource)) == 1
        assert session.scalar(select(func.count()).select_from(MediaDownload)) == 1
        persisted = session.get(ProducerBeat, beat["id"])
        assert persisted is not None and persisted.selected_asset_id == selected["asset_id"]

    storyboard = service.generate_storyboard(workspace["workspace_id"])
    assert Path(storyboard["storyboard_path"]).is_file()
    built = service.build_edit_folder(workspace["workspace_id"])
    with Path(built["edit_folder"]).joinpath("manifest.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        manifest = list(csv.DictReader(handle))
    assert len(manifest) == 1
    assert manifest[0]["source_url"] == file_page
    assert len(list(Path(built["edit_folder"]).joinpath("Visuals").iterdir())) == 1
    assert requests == [
        ("commons.wikimedia.org", "/w/api.php"),
        ("upload.wikimedia.org", "/wikipedia/commons/a/a1/Rendered_form.jpg"),
    ]
    boundary_client.close()
    engine.dispose()


def test_external_import_feedback_keeps_target_beat_and_panel_open(
    catalog_settings: Settings, monkeypatch
) -> None:
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    monkeypatch.setattr(service, "import_external_media", lambda *args, **kwargs: {"asset_id": 1})

    success = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/external",
        data={"direct_media_url": "https://example.test/media.jpg"},
        follow_redirects=True,
    )
    assert b"External media validated, cataloged, and selected." in success.data
    assert b'<details class="sourcing-panel external" open>' in success.data
    assert b'<details class="beat-disclosure" open>' in success.data

    def fail(*args, **kwargs):
        raise ProducerWorkflowError("This URL did not resolve to a supported media file.")

    monkeypatch.setattr(service, "import_external_media", fail)
    failure = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/external",
        data={"direct_media_url": "https://example.test/page.html"},
        follow_redirects=True,
    )
    assert b"did not resolve to a supported media file" in failure.data
    assert b'<details class="sourcing-panel external" open>' in failure.data
    assert b'<details class="beat-disclosure" open>' in failure.data
    engine.dispose()


def test_pexels_import_feedback_keeps_video_url_and_target_beat_open(
    catalog_settings: Settings, monkeypatch
) -> None:
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    video_url = "https://www.pexels.com/video/creepy-night-road-in-forest-18138981/"
    import_pexels_page = service.import_pexels_page
    calls: list[tuple[str, str, str]] = []

    rendered = client.get(f"/stories/{workspace['workspace_id']}")
    form_match = re.search(
        rb'<form action="([^" ]+/pexels)" method="post">\s*'
        rb'<input type="url" name="source_url"[^>]*>\s*'
        rb'<button type="submit">Import &amp; Use</button>',
        rendered.data,
    )
    assert form_match is not None
    action = form_match.group(1).decode()
    assert action == f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/pexels"

    def imported(workspace_id: str, beat_id: str, source_url: str) -> dict[str, int]:
        calls.append((workspace_id, beat_id, source_url))
        return {"asset_id": 91}

    monkeypatch.setattr(service, "import_pexels_page", imported)
    success = client.post(
        action,
        data={"source_url": video_url},
        follow_redirects=True,
    )
    assert calls == [(workspace["workspace_id"], beat["id"], video_url)]
    assert b"Pexels media acquired and selected." in success.data
    assert b'<details class="sourcing-panel pexels" open>' in success.data
    assert b'<details class="beat-disclosure" open>' in success.data

    def unavailable(*args, **kwargs):
        raise ProviderConnectionError("Pexels connection failed")

    monkeypatch.setattr(service, "import_pexels_page", unavailable)
    failure = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/pexels",
        data={"source_url": video_url},
        follow_redirects=True,
    )
    assert b"Pexels import could not be completed: Pexels connection failed" in failure.data
    assert video_url.encode() in failure.data
    assert b'role="alert"' in failure.data
    assert b'<details class="sourcing-panel pexels" open>' in failure.data
    assert b'<details class="beat-disclosure" open>' in failure.data

    monkeypatch.setattr(service, "import_pexels_page", import_pexels_page)
    malformed_url = "https://www.pexels.com/video/creepy-night-road/"
    malformed = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/pexels",
        data={"source_url": malformed_url},
        follow_redirects=True,
    )
    assert b"Pexels import could not be completed: the URL is not a recognized Pexels photo or video page" in malformed.data
    assert malformed_url.encode() in malformed.data
    assert b'<details class="sourcing-panel pexels" open>' in malformed.data
    engine.dispose()


def test_completed_beats_default_collapsed_and_focus_expands(catalog_settings: Settings) -> None:
    engine, _app, client, _service, workspace, beat = _workspace_client(catalog_settings)
    client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/upload",
        data={"media_file": (_jpeg(), "complete.jpg")},
        content_type="multipart/form-data",
    )

    collapsed = client.get(f"/stories/{workspace['workspace_id']}")
    focused = client.get(
        f"/stories/{workspace['workspace_id']}?focus=beat-001&panel=external#beat-001"
    )
    assert b'beat-card completed' in collapsed.data
    assert b'<details class="beat-disclosure" >' in collapsed.data
    assert b'<details class="beat-disclosure" open>' in focused.data
    engine.dispose()


def test_storyboard_generation_persists_controls_and_uses_trusted_paths(
    catalog_settings: Settings,
) -> None:
    opened: list[str] = []
    engine, _app, client, _service, workspace, _beat = _workspace_client(
        catalog_settings, path_opener=opened.append
    )
    workspace_id = workspace["workspace_id"]

    generated = client.post(
        f"/stories/{workspace_id}/storyboard", follow_redirects=True
    )

    assert b"Storyboard generated" in generated.data
    assert b"Storyboard ready" in generated.data
    assert b"Open Folder" in generated.data
    assert b"View" in generated.data
    assert b"toolbar-actions" in generated.data
    assert b'class="production-column"' in generated.data
    view = client.get(f"/stories/{workspace_id}/storyboard/view")
    assert view.status_code == 200
    assert view.mimetype == "application/pdf"
    assert view.data.startswith(b"%PDF")

    client.post(
        f"/stories/{workspace_id}/storyboard/open",
        data={"path": "C:/untrusted/other.pdf"},
    )
    client.post(
        f"/stories/{workspace_id}/storyboard/folder",
        data={"path": "C:/untrusted"},
    )
    expected = catalog_settings.root / "Projects/web-story/Edit/storyboard.pdf"
    assert opened == [str(expected), str(expected.parent)]
    assert expected.is_file()
    engine.dispose()


def test_storyboard_os_open_failure_is_user_facing(
    catalog_settings: Settings,
) -> None:
    def fail_open(path: str) -> None:
        raise OSError("viewer unavailable")

    engine, _app, client, service, workspace, _beat = _workspace_client(
        catalog_settings, path_opener=fail_open
    )
    workspace_id = workspace["workspace_id"]
    service.generate_storyboard(workspace_id)

    response = client.post(
        f"/stories/{workspace_id}/storyboard/open", follow_redirects=True
    )

    assert response.status_code == 200
    assert b"storyboard could not be opened" in response.data
    engine.dispose()


def test_dashboard_organization_and_delete_confirmation(catalog_settings: Settings) -> None:
    engine, _app, client, service, workspace, _beat = _workspace_client(catalog_settings)
    release = service.create_release("EP0001")
    service.assign_workspace_release(workspace["workspace_id"], release["id"])
    service.update_release_metadata(release["id"], status="released", release_date=None)
    dashboard = client.get("/?show_finished=1")
    assert b"In Production" in dashboard.data and b"Planned" in dashboard.data and b"Completed" in dashboard.data
    assert b"EP0001" in dashboard.data
    rejected = client.post(f"/stories/{workspace['workspace_id']}/delete", data={"confirm": "wrong"})
    assert rejected.status_code == 302
    assert service.get_workspace(workspace["workspace_id"], include_candidates=False)["status"] == "completed"
    engine.dispose()


def test_rendered_release_form_create_list_assign_and_refresh(catalog_settings: Settings) -> None:
    engine, _app, client, service, workspace, _beat = _workspace_client(catalog_settings)
    dashboard = client.get("/")
    form = re.search(
        rb'<form action="([^"]*/releases)" method="post">(.*?)</form>',
        dashboard.data,
        re.DOTALL,
    )
    assert form is not None
    assert b"Create release" in dashboard.data
    assert b'placeholder="e.g. ECH-R00001 - Hauntings Behind Horror Movies"' in form.group(2)
    assert b'value="' not in form.group(2)
    names = {item.decode() for item in re.findall(rb'name="([^"]+)"', form.group(2))}
    assert names == {"name"}

    created = client.post(
        form.group(1).decode(),
        data={"name": "EP0001-Hauntings Behind Horror Movies"},
    )
    assert created.status_code == 302
    release = service.list_releases()[0]
    listed = client.get("/")
    assert b"Releases" in listed.data
    assert b"EP0001-Hauntings Behind Horror Movies" in listed.data
    assert b"0 stories" in listed.data

    workspace_page = client.get(f"/stories/{workspace['workspace_id']}")
    assert release["id"].encode() in workspace_page.data
    assigned = client.post(
        f"/stories/{workspace['workspace_id']}/organization/release",
        data={"release_id": release["id"]},
        follow_redirects=True,
    )
    assert b"EP0001-Hauntings Behind Horror Movies" in assigned.data
    refreshed = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert refreshed["release"]["id"] == release["id"]
    assert refreshed["release"]["name"] == release["name"]
    assert refreshed["release"]["status"] == "planned"
    engine.dispose()


def test_release_presentation_and_history_render_without_internal_title_synthesis(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    uploaded = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/upload",
        data={"media_file": (_jpeg(), "release-thumb.jpg")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    with Session(engine) as session:
        asset_id = session.scalar(select(MediaAsset.id).where(MediaAsset.media_type == "image"))
    assert asset_id is not None
    release = service.create_release("Internal Only Name")
    empty = client.get(f"/releases/{release['id']}")
    presentation_section = re.search(
        rb'<section class="presentation-panel surface-panel">(.*?)</section>', empty.data, re.DOTALL
    )
    assert presentation_section is not None
    assert b'name="public_title" value=""' in presentation_section.group(1)
    assert b"internal release name is not used as a public title" in presentation_section.group(1)

    saved = client.post(
        f"/releases/{release['id']}/presentation",
        data={
            "public_title": "Public Release Title",
            "description": "Public description",
            "thumbnail_asset_id": str(asset_id),
            "change_note": "Initial presentation",
        },
        follow_redirects=True,
    )
    assert saved.status_code == 200
    assert b"Public Release Title" in saved.data
    assert b"Presentation revisions (1)" in saved.data
    assert b"Newest first" in saved.data
    workspace_page = client.get(f"/stories/{workspace['workspace_id']}")
    assert b"History" in workspace_page.data
    engine.dispose()


def test_release_thumbnail_upload_reuses_library_ingestion_and_sectioned_ui(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, _workspace, _beat = _workspace_client(catalog_settings)
    release = service.create_release("Thumbnail upload release")
    title = client.post(
        f"/releases/{release['id']}/presentation/title",
        data={"public_title": "A Public Title"},
        follow_redirects=True,
    )
    assert title.status_code == 200
    description = client.post(
        f"/releases/{release['id']}/presentation/description",
        data={"description": "A deliberately long public description. " * 12},
        follow_redirects=True,
    )
    assert description.status_code == 200
    stream = io.BytesIO()
    Image.new("RGB", (160, 90), "teal").save(stream, format="PNG")
    stream.seek(0)
    uploaded = client.post(
        f"/releases/{release['id']}/presentation/thumbnail/upload",
        data={"thumbnail_file": (stream, "fresh-thumbnail.png")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert uploaded.status_code == 200
    assert b"Thumbnail uploaded, cataloged, and selected" in uploaded.data
    assert b"Choose existing" in uploaded.data
    assert b"Add thumbnail" in uploaded.data
    assert b"Show More" in uploaded.data
    assert b"YT-ChannelOps" in uploaded.data
    detail = service.get_release(release["id"])
    thumbnail_id = detail["presentation"]["thumbnail_asset_id"]
    assert thumbnail_id is not None
    with Session(engine) as session:
        asset = session.get(MediaAsset, thumbnail_id)
        assert asset is not None
        assert asset.media_type == "image"
        assert asset.relative_path.startswith("Library/Images/upload-fresh-thumbnail-")
        assert any(source.original_filename == "fresh-thumbnail.png" for source in asset.sources)
        assert session.scalar(
            select(ProducerBeat).where(ProducerBeat.selected_asset_id == thumbnail_id)
        ) is None
    engine.dispose()


def test_released_release_is_not_rendered_as_assignment_option(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, workspace, _beat = _workspace_client(catalog_settings)
    released = service.create_release("Already released")
    active = service.create_release("Still active")
    service.update_release_metadata(released["id"], status="released", release_date=None)
    page = client.get(f"/stories/{workspace['workspace_id']}")
    assignment = re.search(
        rb'<select name="release_id">(.*?)</select>', page.data, re.DOTALL
    )
    assert assignment is not None
    assert active["id"].encode() in assignment.group(1)
    assert released["id"].encode() not in assignment.group(1)
    engine.dispose()


def test_compact_import_navigation_release_metadata_and_finished_filter(catalog_settings: Settings) -> None:
    engine, _app, client, service, workspace, _beat = _workspace_client(catalog_settings)
    dashboard = client.get("/")
    assert b"Import Visual Plan" in dashboard.data
    assert b'<details class="compact-import" >' in dashboard.data
    assert b'class="dashboard-columns three-column-layout"' in dashboard.data
    assert b'class="dashboard-column release-column surface-panel"' in dashboard.data
    assert b'class="dashboard-column story-column"' in dashboard.data
    failed = client.post("/plans", data={}, follow_redirects=True)
    assert b"Choose a Visual Plan JSON file" in failed.data
    assert b'<details class="compact-import" open>' in failed.data

    release = service.create_release("Release metadata")
    service.assign_workspace_release(workspace["workspace_id"], release["id"])
    detail = client.post(
        f"/releases/{release['id']}/metadata",
        data={"status": "in_production", "release_date": "2026-10-31"},
        follow_redirects=True,
    )
    assert b"In Production" in detail.data and b"2026-10-31" in detail.data
    assert b"Stories" in detail.data
    workspace_page = client.get(f"/stories/{workspace['workspace_id']}")
    assert b"Production" in workspace_page.data and b"Release metadata" in workspace_page.data
    service.update_release_metadata(release["id"], status="released", release_date="2026-10-31")
    hidden = client.get("/")
    shown = client.get("/?show_finished=1")
    assert b"Release metadata" not in hidden.data
    assert b"Release metadata" in shown.data and b"Completed" in shown.data
    engine.dispose()


def test_actions_rename_story_is_discoverable_and_preserves_story_identity(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, workspace, _beat = _workspace_client(catalog_settings)
    release = service.create_release("Rename release")
    service.assign_workspace_release(workspace["workspace_id"], release["id"])
    before = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    page = client.get(f"/stories/{workspace['workspace_id']}")
    assert b"Rename" in page.data
    assert b'name="title" value="Web Story"' in page.data
    renamed = client.post(
        f"/stories/{workspace['workspace_id']}/organization/title",
        data={"title": "Renamed Web Story"}, follow_redirects=True,
    )
    assert b"Story display title updated" in renamed.data
    after = service.get_workspace(workspace["workspace_id"], include_candidates=False)
    assert after["title"] == "Renamed Web Story"
    assert after["story_id"] == before["story_id"]
    assert after["workspace_id"] == before["workspace_id"]
    assert after["edit_folder"] == before["edit_folder"]
    assert b"Renamed Web Story" in client.get("/").data
    assert b"Renamed Web Story" in client.get(f"/releases/{release['id']}").data
    engine.dispose()


def test_shared_history_timeline_pages_older_events_and_release_reorder_returns(
    catalog_settings: Settings,
) -> None:
    engine, _app, client, service, workspace, _beat = _workspace_client(catalog_settings)
    release = service.create_release("Timeline release")
    service.assign_workspace_release(workspace["workspace_id"], release["id"])
    for index in range(32):
        service.rename_workspace_title(workspace["workspace_id"], f"Timeline Story {index}")

    recorded_utc = datetime(2027, 1, 15, 18, 5, tzinfo=timezone.utc)
    with Session(engine) as session:
        session.add(
            ProductionEvent(
                id=str(uuid4()),
                subject_type="workspace",
                subject_id=workspace["workspace_id"],
                event_type="workspace.display_time_tested",
                occurred_at=recorded_utc,
                source="test",
                payload_json={},
            )
        )
        session.commit()

    story = client.get(f"/stories/{workspace['workspace_id']}")
    assert story.status_code == 200
    assert b'class="timeline"' in story.data
    assert b"Older events" in story.data
    local_event = recorded_utc.astimezone()
    assert local_event.strftime("%b %d, %Y").encode() in story.data
    assert local_event.strftime("%I:%M %p").lstrip("0").encode() in story.data
    older_story = client.get(f"/stories/{workspace['workspace_id']}?history_offset=30")
    assert older_story.status_code == 200
    assert b"Newer events" in older_story.data

    for index in range(32):
        service.rename_release(release["id"], f"Timeline release {index}")
    release_page = client.get(f"/releases/{release['id']}")
    assert b'class="timeline"' in release_page.data
    assert b"Older events" in release_page.data
    older_release = client.get(f"/releases/{release['id']}?history_offset=30")
    assert b"Newer events" in older_release.data
    moved = client.post(
        f"/stories/{workspace['workspace_id']}/organization/order/up",
        data={"return_to_release": release["id"]},
    )
    assert moved.headers["Location"].endswith(f"/releases/{release['id']}")
    engine.dispose()


def test_existing_media_search_redirects_to_same_local_beat_and_keeps_query(
    catalog_settings: Settings,
) -> None:
    library_file = catalog_settings.root / "Library" / "Images" / "closed-old-door.jpg"
    library_file.parent.mkdir(parents=True, exist_ok=True)
    library_file.write_bytes(_jpeg().read())
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    search = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/search",
        data={"local_query": "closed door"},
    )
    assert search.status_code == 302
    assert "focus=beat-001" in search.headers["Location"]
    assert "panel=local" in search.headers["Location"]
    assert "local_query=closed+door" in search.headers["Location"]
    assert search.headers["Location"].endswith("#beat-001")
    rendered = client.get(search.headers["Location"])
    assert b'value="closed door"' in rendered.data
    assert b'<details class="sourcing-panel local" open>' in rendered.data
    assert b'<details class="beat-disclosure" open>' in rendered.data
    assert b"Catalog asset" in rendered.data

    no_results = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/search",
        data={"local_query": "nothing-matches-this"},
        follow_redirects=True,
    )
    assert b"No existing catalog media matched" in no_results.data
    assert b"No matching existing catalog media" in no_results.data
    assert b'<details class="sourcing-panel local" open>' in no_results.data
    empty = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/search",
        data={"local_query": ""}, follow_redirects=True,
    )
    assert b"Enter a catalog search term" in empty.data
    assert b'<details class="sourcing-panel local" open>' in empty.data
    engine.dispose()


def test_incompatible_catalog_selection_is_visible_and_can_be_overridden(catalog_settings: Settings) -> None:
    engine, _app, client, service, workspace, beat = _workspace_client(catalog_settings)
    video_path = catalog_settings.root / "Library" / "Videos" / "route-video.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    video_path.write_bytes(b"route-test-video")
    sha256 = hashlib.sha256(video_path.read_bytes()).hexdigest()
    with Session(engine) as session:
        asset = MediaAsset(
            relative_path="Library/Videos/route-video.mp4", media_type="video", status="active",
            file_size_bytes=video_path.stat().st_size, sha256=sha256,
        )
        session.add(asset)
        session.flush()
        session.add(MediaLocation(
            media_asset_id=asset.id, relative_path="Library/Videos/route-video.mp4",
            status="available", provenance_type="local_import", file_size_bytes=video_path.stat().st_size,
        ))
        session.commit()
        asset_id = asset.id
    failed = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/select/{asset_id}",
        follow_redirects=True,
    )
    assert b"currently prefers an image" in failed.data
    assert b'<details class="sourcing-panel local" open>' in failed.data
    assert b'<details class="beat-disclosure" open>' in failed.data
    overridden = client.post(
        f"/stories/{workspace['workspace_id']}/beats/{beat['id']}/select/{asset_id}",
        data={"override_media_preference": "1"}, follow_redirects=True,
    )
    assert b"Asset selected for this beat" in overridden.data
    assert service.get_workspace(workspace["workspace_id"], include_candidates=False)["beats"][0]["specification"]["media_preference"] == "video"
    engine.dispose()
