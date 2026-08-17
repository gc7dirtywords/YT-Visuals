from __future__ import annotations

import httpx
import pytest

from yt_visuals.providers.errors import (
    MissingProviderCredentialError,
    ProviderAuthenticationError,
    ProviderConnectionError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from yt_visuals.providers.pexels import PexelsProvider


PHOTO = {
    "id": 2014422,
    "width": 3024,
    "height": 3024,
    "url": "https://www.pexels.com/photo/brown-rocks-2014422/",
    "photographer": "Joey Farina",
    "photographer_url": "https://www.pexels.com/@joey",
    "photographer_id": 680589,
    "avg_color": "#978E82",
    "src": {
        "original": "https://images.pexels.com/photos/2014422/pexels-photo-2014422.jpeg",
        "medium": "https://images.pexels.com/photos/2014422/pexels-photo-2014422.jpeg?h=350",
    },
    "alt": "Brown rocks during golden hour",
}

VIDEO = {
    "id": 2499611,
    "width": 1080,
    "height": 1920,
    "url": "https://www.pexels.com/video/2499611/",
    "image": "https://images.pexels.com/videos/2499611/preview.jpg",
    "duration": 22,
    "user": {"id": 680589, "name": "Joey Farina", "url": "https://www.pexels.com/@joey"},
    "video_files": [
        {
            "id": 1,
            "quality": "sd",
            "file_type": "video/mp4",
            "width": 540,
            "height": 960,
            "fps": 23.976,
            "link": "https://videos.pexels.test/2499611-sd.mp4",
        },
        {
            "id": 2,
            "quality": "hd",
            "file_type": "video/mp4",
            "width": 1080,
            "height": 1920,
            "fps": 23.976,
            "link": "https://videos.pexels.test/2499611-hd.mp4",
        },
    ],
    "video_pictures": [],
}


def provider_for(handler: httpx.MockTransport) -> PexelsProvider:
    return PexelsProvider("test-key", client=httpx.Client(transport=handler))


def test_normalizes_photo_results_and_search_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "test-key"
        assert request.url.path == "/v1/search"
        assert request.url.params["query"] == "abandoned factory"
        assert request.url.params["orientation"] == "landscape"
        assert request.url.params["size"] == "large"
        assert request.url.params["color"] == "gray"
        assert request.url.params["page"] == "2"
        assert request.url.params["per_page"] == "40"
        return httpx.Response(
            200,
            headers={"X-Ratelimit-Remaining": "199"},
            json={
                "page": 2,
                "per_page": 40,
                "total_results": 81,
                "photos": [PHOTO],
                "prev_page": "https://api.pexels.com/v1/search?page=1",
                "next_page": "https://api.pexels.com/v1/search?page=3",
            },
        )

    provider = provider_for(httpx.MockTransport(handler))
    page = provider.search_photos(
        "abandoned factory",
        orientation="landscape",
        size="large",
        color="gray",
        page=2,
        per_page=40,
    )

    assert page.page == 2
    assert page.next_page is not None
    assert page.previous_page is not None
    assert page.provider_metadata == {
        "rate_limit": None,
        "rate_limit_remaining": "199",
        "rate_limit_reset": None,
    }
    result = page.results[0]
    assert result.provider == "pexels"
    assert result.provider_asset_id == "2014422"
    assert result.catalog_source_id == "photo:2014422"
    assert result.media_type == "image"
    assert result.title == "Brown rocks during golden hour"
    assert result.creator_name == "Joey Farina"
    assert result.download_url.endswith(".jpeg")
    assert result.preview_url is not None
    assert result.width == 3024
    assert result.height == 3024
    assert result.mime_type == "image/jpeg"
    assert result.attribution_required is False
    assert result.commercial_use_allowed is True


def test_normalizes_video_results_and_selects_largest_mp4() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/videos/search"
        assert request.url.params["orientation"] == "portrait"
        return httpx.Response(
            200,
            json={"page": 1, "per_page": 15, "total_results": 1, "videos": [VIDEO]},
        )

    provider = provider_for(httpx.MockTransport(handler))
    result = provider.search_videos("storm clouds", orientation="portrait").results[0]

    assert result.catalog_source_id == "video:2499611"
    assert result.media_type == "video"
    assert result.download_url.endswith("2499611-hd.mp4")
    assert result.preview_url == VIDEO["image"]
    assert (result.width, result.height) == (1080, 1920)
    assert result.duration_ms == 22_000
    assert result.mime_type == "video/mp4"
    assert result.creator_url == "https://www.pexels.com/@joey"


def test_empty_search_is_valid() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, json={"page": 1, "per_page": 15, "total_results": 0, "photos": []}
        )
    )
    page = provider_for(transport).search_photos("nothing here")
    assert page.results == ()
    assert page.total_results == 0


def test_get_photo_and_video_use_current_v1_endpoints() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json=PHOTO if "photos" in request.url.path else VIDEO)

    provider = provider_for(httpx.MockTransport(handler))
    assert provider.get_photo("2014422").media_type == "image"
    assert provider.get_video("2499611").media_type == "video"
    assert paths == ["/v1/photos/2014422", "/v1/videos/videos/2499611"]


def test_missing_api_key_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    provider = PexelsProvider(client=httpx.Client(transport=httpx.MockTransport(lambda r: None)))
    with pytest.raises(MissingProviderCredentialError, match="PEXELS_API_KEY"):
        provider.search_photos("factory")


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_failure(status: int) -> None:
    provider = provider_for(httpx.MockTransport(lambda request: httpx.Response(status)))
    with pytest.raises(ProviderAuthenticationError, match="rejected"):
        provider.search_photos("factory")


def test_rate_limit_failure_exposes_reset_hint() -> None:
    provider = provider_for(
        httpx.MockTransport(
            lambda request: httpx.Response(429, headers={"Retry-After": "120"})
        )
    )
    with pytest.raises(ProviderRateLimitError) as error:
        provider.search_videos("clouds")
    assert error.value.reset_at == "120"


def test_malformed_json_and_unexpected_structure() -> None:
    malformed = provider_for(
        httpx.MockTransport(lambda request: httpx.Response(200, content=b"{not-json"))
    )
    with pytest.raises(ProviderResponseError, match="malformed JSON"):
        malformed.search_photos("factory")

    unexpected = provider_for(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"page": 1, "per_page": 15, "total_results": 0}
            )
        )
    )
    with pytest.raises(ProviderResponseError, match="photos array"):
        unexpected.search_photos("factory")


def test_connection_failure_and_timeout_are_mapped() -> None:
    def connection_failure(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    provider = provider_for(httpx.MockTransport(connection_failure))
    with pytest.raises(ProviderConnectionError, match="connect"):
        provider.search_photos("factory")

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    provider = provider_for(httpx.MockTransport(timeout))
    with pytest.raises(ProviderTimeoutError, match="timed out"):
        provider.search_photos("factory")
