from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import httpx

from yt_visuals.config import Settings

from .base import MediaProvider, ProviderInfo
from .errors import ProviderRequestError
from .pexels import PexelsProvider


@dataclass(frozen=True, slots=True)
class ProviderRegistration:
    info: ProviderInfo
    configured: bool

    def to_dict(self) -> dict[str, object]:
        return {**self.info.to_dict(), "configured": self.configured}


def list_providers(settings: Settings) -> tuple[ProviderRegistration, ...]:
    return (ProviderRegistration(PexelsProvider.INFO, configured=bool(settings.pexels_api_key)),)


def create_provider(
    name: str, settings: Settings, *, http_client: httpx.Client | None = None
) -> MediaProvider:
    normalized = name.strip().lower()
    factories: dict[str, Callable[[], MediaProvider]] = {
        "pexels": lambda: PexelsProvider(settings.pexels_api_key, client=http_client),
    }
    factory = factories.get(normalized)
    if factory is None:
        available = ", ".join(sorted(factories))
        raise ProviderRequestError(f"Unknown provider '{name}'. Available providers: {available}")
    return factory()
