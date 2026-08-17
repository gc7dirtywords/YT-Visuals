from __future__ import annotations

import json

from yt_visuals.acquisition import AcquisitionOutcome
from yt_visuals.cli import cli
from yt_visuals.config import Settings
from yt_visuals.providers.base import MediaSearchResult, ProviderInfo, SearchPage


RESULT = MediaSearchResult(
    provider="pexels",
    provider_asset_id="42",
    media_type="image",
    title="Factory",
    description=None,
    creator_name="Alex",
    creator_url=None,
    source_url="https://www.pexels.com/photo/42/",
    download_url="https://images.pexels.test/42.jpg",
    preview_url="https://images.pexels.test/42-preview.jpg",
    width=1920,
    height=1080,
    duration_ms=None,
    mime_type="image/jpeg",
    license_name="Pexels License",
    license_url="https://www.pexels.com/legal-pages/license/",
    attribution_required=False,
    attribution_text="Photo by Alex on Pexels",
    raw_metadata={"id": 42},
)


class FakeProvider:
    info = ProviderInfo(
        name="pexels",
        display_name="Pexels",
        website_url="https://www.pexels.com/",
        api_url="https://www.pexels.com/api/",
        license_name="Pexels License",
        license_url="https://www.pexels.com/legal-pages/license/",
        attribution_required=False,
    )

    def __init__(self) -> None:
        self.closed = False

    def search_photos(self, query: str, **kwargs: object) -> SearchPage:
        assert query == "abandoned factory"
        assert kwargs["page"] == 2
        return SearchPage((RESULT,), page=2, per_page=15, total_results=16)

    def search_videos(self, query: str, **kwargs: object) -> SearchPage:
        return SearchPage((), page=1, per_page=15, total_results=0)

    def get_photo(self, provider_asset_id: str) -> MediaSearchResult:
        assert provider_asset_id == "42"
        return RESULT

    def get_video(self, provider_asset_id: str) -> MediaSearchResult:
        raise AssertionError("not used")

    def close(self) -> None:
        self.closed = True


class FakeAcquisitionService:
    def __init__(self, settings: Settings, engine: object) -> None:
        self.acquired: MediaSearchResult | None = None

    def find_existing(
        self, provider: str, media_type: str, provider_asset_id: str
    ) -> AcquisitionOutcome | None:
        return None

    def acquire(self, result: MediaSearchResult) -> AcquisitionOutcome:
        self.acquired = result
        return AcquisitionOutcome(
            asset_id=7,
            relative_path="Library/Images/pexels-photo-42.jpg",
            sha256="a" * 64,
            file_size_bytes=123,
            created_asset=True,
            created_source=True,
        )

    def close(self) -> None:
        pass


def test_providers_command_is_safe_without_api_key(
    catalog_settings: Settings, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    assert cli(["providers"], settings=catalog_settings) == 0
    output = capsys.readouterr().out
    assert "pexels: Pexels" in output
    assert "missing PEXELS_API_KEY" in output


def test_cli_search_human_and_json_output(catalog_settings: Settings, capsys) -> None:  # type: ignore[no-untyped-def]
    factory = lambda name, settings: FakeProvider()
    assert (
        cli(
            ["search", "pexels", "photos", "abandoned factory", "--page", "2"],
            settings=catalog_settings,
            provider_factory=factory,
        )
        == 0
    )
    human = capsys.readouterr().out
    assert "42: Factory" in human
    assert "yt-visuals download pexels photos 42" in human

    assert (
        cli(
            ["search", "pexels", "photos", "abandoned factory", "--page", "2", "--json"],
            settings=catalog_settings,
            provider_factory=factory,
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["page"] == 2
    assert payload["results"][0]["provider_asset_id"] == "42"


def test_cli_download(catalog_settings: Settings, capsys) -> None:  # type: ignore[no-untyped-def]
    assert (
        cli(
            ["download", "pexels", "photos", "42", "--json"],
            settings=catalog_settings,
            provider_factory=lambda name, settings: FakeProvider(),
            acquisition_factory=FakeAcquisitionService,
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["asset_id"] == 7
    assert payload["created_asset"] is True
    assert payload["relative_path"].startswith("Library/Images/")
