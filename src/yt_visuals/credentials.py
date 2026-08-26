from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import keyring
from keyring.errors import KeyringError, PasswordDeleteError


SERVICE_NAME = "YT-Visuals"
PEXELS_CREDENTIAL_NAME = "PEXELS_API_KEY"


class CredentialStoreError(RuntimeError):
    """A credential backend operation failed without exposing secret material."""


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    configured: bool
    source: str
    error: str | None = None


class CredentialStore:
    """Small keyring-backed store for local integration credentials."""

    def __init__(self, backend: Any = keyring) -> None:
        self.backend = backend

    def pexels_status(self) -> CredentialStatus:
        if _environment_key():
            return CredentialStatus(True, "environment")
        try:
            configured = bool(self._stored_pexels_key())
        except CredentialStoreError:
            return CredentialStatus(
                False,
                "none",
                "Windows Credential Manager is unavailable.",
            )
        return CredentialStatus(configured, "keyring" if configured else "none")

    def resolve_pexels_api_key(self) -> str | None:
        environment = _environment_key()
        if environment:
            return environment
        return self._stored_pexels_key()

    def save_pexels_api_key(self, value: str) -> None:
        secret = value.strip()
        if not secret:
            raise CredentialStoreError("Enter a Pexels API key before saving.")
        try:
            self.backend.set_password(SERVICE_NAME, PEXELS_CREDENTIAL_NAME, secret)
        except KeyringError as exc:
            raise CredentialStoreError(
                "The Pexels key could not be saved to Windows Credential Manager."
            ) from exc

    def remove_pexels_api_key(self) -> bool:
        try:
            if not self._stored_pexels_key():
                return False
            self.backend.delete_password(SERVICE_NAME, PEXELS_CREDENTIAL_NAME)
            return True
        except PasswordDeleteError:
            return False
        except KeyringError as exc:
            raise CredentialStoreError(
                "The Pexels key could not be removed from Windows Credential Manager."
            ) from exc

    def _stored_pexels_key(self) -> str | None:
        try:
            value = self.backend.get_password(SERVICE_NAME, PEXELS_CREDENTIAL_NAME)
        except KeyringError as exc:
            raise CredentialStoreError(
                "Windows Credential Manager could not be read."
            ) from exc
        cleaned = value.strip() if isinstance(value, str) else ""
        return cleaned or None


def resolve_pexels_api_key() -> str | None:
    try:
        return CredentialStore().resolve_pexels_api_key()
    except CredentialStoreError:
        return None


def _environment_key() -> str | None:
    value = os.environ.get(PEXELS_CREDENTIAL_NAME, "").strip()
    return value or None
