from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol


MediaType = Literal["image", "video"]


@dataclass(frozen=True, slots=True)
class ProviderInfo:
    name: str
    display_name: str
    website_url: str
    api_url: str
    license_name: str
    license_url: str
    attribution_required: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MediaSearchResult:
    provider: str
    provider_asset_id: str
    media_type: MediaType
    title: str | None
    description: str | None
    creator_name: str | None
    creator_url: str | None
    source_url: str
    download_url: str
    preview_url: str | None
    width: int | None
    height: int | None
    duration_ms: int | None
    mime_type: str | None
    license_name: str
    license_url: str
    attribution_required: bool
    attribution_text: str | None
    raw_metadata: dict[str, Any]
    commercial_use_allowed: bool | None = None
    modifications_allowed: bool | None = None
    license_notes: str | None = None

    @property
    def catalog_source_id(self) -> str:
        kind = "photo" if self.media_type == "image" else "video"
        return f"{kind}:{self.provider_asset_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SearchPage:
    results: tuple[MediaSearchResult, ...]
    page: int
    per_page: int
    total_results: int
    next_page: str | None = None
    previous_page: str | None = None
    provider_metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "results": [result.to_dict() for result in self.results],
            "page": self.page,
            "per_page": self.per_page,
            "total_results": self.total_results,
            "next_page": self.next_page,
            "previous_page": self.previous_page,
            "provider_metadata": self.provider_metadata or {},
        }


class MediaProvider(Protocol):
    @property
    def info(self) -> ProviderInfo: ...

    def search_photos(
        self,
        query: str,
        *,
        orientation: str | None = None,
        size: str | None = None,
        color: str | None = None,
        page: int = 1,
        per_page: int = 15,
    ) -> SearchPage: ...

    def search_videos(
        self,
        query: str,
        *,
        orientation: str | None = None,
        size: str | None = None,
        page: int = 1,
        per_page: int = 15,
    ) -> SearchPage: ...

    def get_photo(self, provider_asset_id: str) -> MediaSearchResult: ...

    def get_video(self, provider_asset_id: str) -> MediaSearchResult: ...

    def close(self) -> None: ...
