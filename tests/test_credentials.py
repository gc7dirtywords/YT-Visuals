from __future__ import annotations

from yt_visuals.credentials import (
    PEXELS_CREDENTIAL_NAME,
    SERVICE_NAME,
    CredentialStore,
)
from yt_visuals.config import Settings


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.calls: list[tuple[str, str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.calls.append(("get", service, username))
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.calls.append(("set", service, username))
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.calls.append(("delete", service, username))
        del self.values[(service, username)]


def test_keyring_credential_lifecycle_uses_fixed_identity(monkeypatch) -> None:
    monkeypatch.delenv(PEXELS_CREDENTIAL_NAME, raising=False)
    backend = FakeKeyring()
    store = CredentialStore(backend)

    assert store.pexels_status().source == "none"
    store.save_pexels_api_key("  stored-secret  ")
    assert store.resolve_pexels_api_key() == "stored-secret"
    assert store.pexels_status().source == "keyring"
    assert store.remove_pexels_api_key() is True
    assert store.resolve_pexels_api_key() is None
    assert all(call[1:] == (SERVICE_NAME, PEXELS_CREDENTIAL_NAME) for call in backend.calls)


def test_environment_credential_takes_precedence_without_modifying_keyring(monkeypatch) -> None:
    backend = FakeKeyring()
    backend.values[(SERVICE_NAME, PEXELS_CREDENTIAL_NAME)] = "stored-secret"
    store = CredentialStore(backend)
    monkeypatch.setenv(PEXELS_CREDENTIAL_NAME, "environment-secret")

    assert store.resolve_pexels_api_key() == "environment-secret"
    status = store.pexels_status()
    assert status.configured is True
    assert status.source == "environment"
    assert backend.calls == []


def test_settings_resolves_keyring_when_environment_is_absent(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv(PEXELS_CREDENTIAL_NAME, raising=False)
    monkeypatch.setattr(
        "yt_visuals.credentials.keyring.get_password",
        lambda service, username: "keyring-secret",
    )

    assert Settings(root=tmp_path).pexels_api_key == "keyring-secret"
