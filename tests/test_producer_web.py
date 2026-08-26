from __future__ import annotations

import io

from PIL import Image

from yt_visuals.config import Settings
from yt_visuals.credentials import CredentialStore, PEXELS_CREDENTIAL_NAME, SERVICE_NAME
from yt_visuals.database import initialize_database
from yt_visuals.providers.errors import ProviderAuthenticationError, ProviderConnectionError
from yt_visuals.producer.web import create_app


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


def _jpeg() -> io.BytesIO:
    stream = io.BytesIO()
    Image.new("RGB", (120, 68), "brown").save(stream, format="JPEG")
    stream.seek(0)
    return stream


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
    assert client.get("/static/producer.css").status_code == 200
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
