from __future__ import annotations

import json
import mimetypes
import os
import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from .base import MediaSearchResult, ProviderInfo, SearchPage
from .errors import (
    MissingProviderCredentialError,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderNotFoundError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderTimeoutError,
)


ORIENTATIONS = {"landscape", "portrait", "square"}
SIZES = {"large", "medium", "small"}
COLORS = {
    "red",
    "orange",
    "yellow",
    "green",
    "turquoise",
    "blue",
    "violet",
    "pink",
    "brown",
    "black",
    "gray",
    "white",
}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class PexelsProvider:
    API_BASE_URL = "https://api.pexels.com"
    INFO = ProviderInfo(
        name="pexels",
        display_name="Pexels",
        website_url="https://www.pexels.com/",
        api_url="https://www.pexels.com/api/",
        license_name="Pexels License",
        license_url="https://www.pexels.com/legal-pages/license/",
        attribution_required=False,
    )

    def __init__(
        self,
        api_key: str | None = None,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.api_key = (api_key if api_key is not None else os.environ.get("PEXELS_API_KEY", "")).strip()
        self.timeout_seconds = timeout_seconds
        self._owns_client = client is None
        self.client = client or httpx.Client(follow_redirects=True)

    @property
    def info(self) -> ProviderInfo:
        return self.INFO

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def search_photos(
        self,
        query: str,
        *,
        orientation: str | None = None,
        size: str | None = None,
        color: str | None = None,
        page: int = 1,
        per_page: int = 15,
    ) -> SearchPage:
        params = self._search_params(query, orientation, size, page, per_page)
        if color is not None:
            if color not in COLORS and not HEX_COLOR.fullmatch(color):
                raise ProviderRequestError("Pexels color must be a supported name or #RRGGBB value")
            params["color"] = color
        payload, headers = self._request_json("/v1/search", params=params)
        return self._normalize_page(payload, headers, collection_name="photos", normalizer=self._normalize_photo)

    def search_videos(
        self,
        query: str,
        *,
        orientation: str | None = None,
        size: str | None = None,
        page: int = 1,
        per_page: int = 15,
    ) -> SearchPage:
        params = self._search_params(query, orientation, size, page, per_page)
        payload, headers = self._request_json("/v1/videos/search", params=params)
        return self._normalize_page(payload, headers, collection_name="videos", normalizer=self._normalize_video)

    def get_photo(self, provider_asset_id: str) -> MediaSearchResult:
        asset_id = self._asset_id(provider_asset_id)
        payload, _headers = self._request_json(f"/v1/photos/{asset_id}")
        return self._normalize_photo(payload)

    def get_video(self, provider_asset_id: str) -> MediaSearchResult:
        asset_id = self._asset_id(provider_asset_id)
        payload, _headers = self._request_json(f"/v1/videos/videos/{asset_id}")
        return self._normalize_video(payload)

    def _request_json(
        self, path: str, *, params: dict[str, str | int] | None = None
    ) -> tuple[dict[str, Any], httpx.Headers]:
        if not self.api_key:
            raise MissingProviderCredentialError(
                "PEXELS_API_KEY is not set; configure it in the environment before using Pexels"
            )
        try:
            response = self.client.get(
                f"{self.API_BASE_URL}{path}",
                params=params,
                headers={"Authorization": self.api_key},
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError("Pexels request timed out") from exc
        except httpx.RequestError as exc:
            raise ProviderConnectionError(f"Could not connect to Pexels: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthenticationError("Pexels rejected the API key")
        if response.status_code == 404:
            raise ProviderNotFoundError("The requested Pexels asset was not found")
        if response.status_code == 429:
            reset_at = response.headers.get("X-Ratelimit-Reset") or response.headers.get("Retry-After")
            raise ProviderRateLimitError("Pexels API rate limit exceeded", reset_at=reset_at)
        if 400 <= response.status_code < 500:
            raise ProviderRequestError(
                f"Pexels rejected the request with HTTP {response.status_code}: {self._safe_error(response)}"
            )
        if response.status_code >= 500:
            raise ProviderResponseError(f"Pexels returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderResponseError("Pexels returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderResponseError("Pexels returned an unexpected JSON document")
        return payload, response.headers

    @staticmethod
    def _safe_error(response: httpx.Response) -> str:
        text = response.text.strip().replace("\r", " ").replace("\n", " ")
        return text[:240] or "no error details"

    @staticmethod
    def _search_params(
        query: str, orientation: str | None, size: str | None, page: int, per_page: int
    ) -> dict[str, str | int]:
        query = query.strip()
        if not query:
            raise ProviderRequestError("Search query must not be empty")
        if orientation is not None and orientation not in ORIENTATIONS:
            raise ProviderRequestError(f"Unsupported orientation: {orientation}")
        if size is not None and size not in SIZES:
            raise ProviderRequestError(f"Unsupported size: {size}")
        if page < 1:
            raise ProviderRequestError("Page must be at least 1")
        if not 1 <= per_page <= 80:
            raise ProviderRequestError("per_page must be between 1 and 80")
        params: dict[str, str | int] = {"query": query, "page": page, "per_page": per_page}
        if orientation is not None:
            params["orientation"] = orientation
        if size is not None:
            params["size"] = size
        return params

    @staticmethod
    def _asset_id(value: str) -> str:
        value = str(value).strip()
        if not value or not value.isdigit():
            raise ProviderRequestError("Pexels asset ID must be numeric")
        return value

    def _normalize_page(
        self,
        payload: dict[str, Any],
        headers: httpx.Headers,
        *,
        collection_name: str,
        normalizer: Any,
    ) -> SearchPage:
        collection = payload.get(collection_name)
        if not isinstance(collection, list):
            raise ProviderResponseError(f"Pexels response is missing the {collection_name} array")
        page = self._required_int(payload, "page")
        per_page = self._required_int(payload, "per_page")
        total_results = self._required_int(payload, "total_results")
        results = tuple(normalizer(item) for item in collection)
        return SearchPage(
            results=results,
            page=page,
            per_page=per_page,
            total_results=total_results,
            next_page=self._optional_string(payload.get("next_page")),
            previous_page=self._optional_string(payload.get("prev_page")),
            provider_metadata={
                "rate_limit": headers.get("X-Ratelimit-Limit"),
                "rate_limit_remaining": headers.get("X-Ratelimit-Remaining"),
                "rate_limit_reset": headers.get("X-Ratelimit-Reset"),
            },
        )

    def _normalize_photo(self, item: Any) -> MediaSearchResult:
        if not isinstance(item, dict):
            raise ProviderResponseError("Pexels photo entry is not an object")
        asset_id = str(self._required_int(item, "id"))
        source_url = self._required_string(item, "url")
        sources = item.get("src")
        if not isinstance(sources, dict):
            raise ProviderResponseError("Pexels photo is missing its src object")
        download_url = self._required_string(sources, "original")
        creator = self._optional_string(item.get("photographer"))
        return MediaSearchResult(
            provider=self.info.name,
            provider_asset_id=asset_id,
            media_type="image",
            title=self._optional_string(item.get("alt")),
            description=None,
            creator_name=creator,
            creator_url=self._optional_string(item.get("photographer_url")),
            source_url=source_url,
            download_url=download_url,
            preview_url=self._optional_string(sources.get("medium") or sources.get("small")),
            width=self._required_int(item, "width"),
            height=self._required_int(item, "height"),
            duration_ms=None,
            mime_type=self._mime_from_url(download_url),
            license_name=self.info.license_name,
            license_url=self.info.license_url,
            attribution_required=self.info.attribution_required,
            attribution_text=f"Photo by {creator} on Pexels" if creator else "Photo from Pexels",
            raw_metadata=dict(item),
            commercial_use_allowed=True,
            modifications_allowed=True,
            license_notes=(
                "Attribution is optional but appreciated; review the Pexels License. "
                "This mapping does not clear people, property, trademark, logo, sensitive-context, "
                "or other third-party rights."
            ),
        )

    def _normalize_video(self, item: Any) -> MediaSearchResult:
        if not isinstance(item, dict):
            raise ProviderResponseError("Pexels video entry is not an object")
        asset_id = str(self._required_int(item, "id"))
        source_url = self._required_string(item, "url")
        files = item.get("video_files")
        if not isinstance(files, list):
            raise ProviderResponseError("Pexels video is missing its video_files array")
        usable_files = [entry for entry in files if isinstance(entry, dict) and entry.get("link")]
        if not usable_files:
            raise ProviderResponseError("Pexels video has no downloadable file")
        mp4_files = [entry for entry in usable_files if entry.get("file_type") == "video/mp4"]
        selected = max(mp4_files or usable_files, key=self._video_file_rank)
        user = item.get("user") if isinstance(item.get("user"), dict) else {}
        creator = self._optional_string(user.get("name"))
        duration = item.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
            raise ProviderResponseError("Pexels video has an invalid duration")
        return MediaSearchResult(
            provider=self.info.name,
            provider_asset_id=asset_id,
            media_type="video",
            title=None,
            description=None,
            creator_name=creator,
            creator_url=self._optional_string(user.get("url")),
            source_url=source_url,
            download_url=self._required_string(selected, "link"),
            preview_url=self._optional_string(item.get("image")),
            width=self._optional_int(selected.get("width")) or self._optional_int(item.get("width")),
            height=self._optional_int(selected.get("height")) or self._optional_int(item.get("height")),
            duration_ms=round(duration * 1000),
            mime_type=self._optional_string(selected.get("file_type")) or self._mime_from_url(
                self._required_string(selected, "link")
            ),
            license_name=self.info.license_name,
            license_url=self.info.license_url,
            attribution_required=self.info.attribution_required,
            attribution_text=f"Video by {creator} on Pexels" if creator else "Video from Pexels",
            raw_metadata=dict(item),
            commercial_use_allowed=True,
            modifications_allowed=True,
            license_notes=(
                "Attribution is optional but appreciated; review the Pexels License. "
                "This mapping does not clear people, property, trademark, logo, sensitive-context, "
                "or other third-party rights."
            ),
        )

    @staticmethod
    def _video_file_rank(item: dict[str, Any]) -> tuple[int, int, float]:
        width = PexelsProvider._optional_int(item.get("width")) or 0
        height = PexelsProvider._optional_int(item.get("height")) or 0
        fps = item.get("fps") if isinstance(item.get("fps"), (int, float)) else 0.0
        return width * height, width, float(fps)

    @staticmethod
    def _required_int(item: dict[str, Any], key: str) -> int:
        value = item.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ProviderResponseError(f"Pexels response has an invalid {key}")
        return value

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None

    @staticmethod
    def _required_string(item: dict[str, Any], key: str) -> str:
        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ProviderResponseError(f"Pexels response has an invalid {key}")
        return value.strip()

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _mime_from_url(url: str) -> str | None:
        mime_type, _encoding = mimetypes.guess_type(urlsplit(url).path)
        return mime_type
