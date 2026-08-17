from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from yt_visuals.acquisition import AcquisitionService, ProbeResult, safe_filename
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.models import AssetLicense, MediaAsset, MediaDownload, MediaProvider, MediaSource
from yt_visuals.providers.base import MediaSearchResult
from yt_visuals.providers.errors import MediaDownloadError


def photo_result(asset_id: str = "42") -> MediaSearchResult:
    return MediaSearchResult(
        provider="pexels",
        provider_asset_id=asset_id,
        media_type="image",
        title="Abandoned Factory / Exterior",
        description="Industrial building",
        creator_name="Alex Example",
        creator_url="https://www.pexels.com/@alex",
        source_url=f"https://www.pexels.com/photo/{asset_id}/",
        download_url=f"https://images.pexels.test/{asset_id}.jpeg",
        preview_url=f"https://images.pexels.test/{asset_id}-preview.jpeg",
        width=1920,
        height=1080,
        duration_ms=None,
        mime_type="image/jpeg",
        license_name="Pexels License",
        license_url="https://www.pexels.com/legal-pages/license/",
        attribution_required=False,
        attribution_text="Photo by Alex Example on Pexels",
        raw_metadata={"id": int(asset_id), "test": True},
        commercial_use_allowed=True,
        modifications_allowed=True,
        license_notes="Attribution is optional but appreciated.",
    )


class CountingStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.yield_count = 0

    def __iter__(self):  # type: ignore[no-untyped-def]
        for chunk in self.chunks:
            self.yield_count += 1
            yield chunk


def test_streamed_download_hash_safe_filename_and_catalog_insertion(
    catalog_settings: Settings,
) -> None:
    chunks = [b"first-", b"second-", b"third"]
    stream = CountingStream(chunks)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"Content-Type": "image/jpeg; charset=binary"}, stream=stream
            )
        )
    )
    engine = initialize_database(catalog_settings)
    service = AcquisitionService(catalog_settings, engine, http_client=client)

    result = replace(
        photo_result(),
        raw_metadata={
            "id": 42,
            "Authorization": "Bearer test-only-placeholder",
            "nested": {"api_key": "test-only-placeholder", "safe": "retained"},
        },
    )
    outcome = service.acquire(result)

    content = b"".join(chunks)
    assert stream.yield_count == 3
    assert outcome.sha256 == hashlib.sha256(content).hexdigest()
    assert outcome.file_size_bytes == len(content)
    assert outcome.created_asset is True
    assert outcome.relative_path.startswith("Library/Images/")
    assert ".." not in outcome.relative_path
    downloaded = catalog_settings.root / outcome.relative_path
    assert downloaded.read_bytes() == content

    with Session(engine) as session:
        asset = session.get(MediaAsset, outcome.asset_id)
        assert asset is not None
        assert asset.relative_path == outcome.relative_path
        assert asset.mime_type == "image/jpeg"
        assert (asset.width, asset.height) == (1920, 1080)
        assert asset.sources[0].provider_asset_id == "photo:42"
        assert asset.sources[0].source_url == "https://www.pexels.com/photo/42/"
        assert asset.license is not None
        assert asset.license.attribution_required is False
        assert asset.license.attribution_text == "Photo by Alex Example on Pexels"
        history = session.get(MediaDownload, outcome.download_history_id)
        assert history is not None
        assert history.status == "success"
        assert history.provider == "pexels"
        assert history.provider_asset_id == "42"
        assert history.media_type == "image"
        assert history.source_url == "https://www.pexels.com/photo/42/"
        assert history.download_url == "https://images.pexels.test/42.jpeg"
        assert history.attempted_at is not None
        assert history.completed_at is not None
        assert history.completed_at >= history.attempted_at
        assert history.asset is asset
        assert history.relative_path == asset.relative_path
        assert history.relative_path.startswith("Library/Images/")
        assert history.sha256 == outcome.sha256
        assert history.downloaded_bytes == len(content)
        assert history.http_status_code == 200
        assert history.content_type == "image/jpeg; charset=binary"
        assert history.request_metadata["network_transfer"] is True
        serialized_metadata = json.dumps(history.provider_metadata).lower()
        assert "authorization" not in serialized_metadata
        assert "api_key" not in serialized_metadata
        assert "test-only-placeholder" not in serialized_metadata
        assert history.provider_metadata["nested"]["safe"] == "retained"
    engine.dispose()


def test_safe_filename_removes_path_and_windows_unsafe_characters() -> None:
    result = replace(photo_result(), title="../../CON: bad ♥ name???")
    filename = safe_filename(result, "image/jpeg", "a" * 64)
    assert filename == "pexels-photo-42-con-bad-name-aaaaaaaaaa.jpg"
    assert "/" not in filename
    assert "\\" not in filename


def test_same_provider_asset_is_not_downloaded_twice(catalog_settings: Settings) -> None:
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"asset")

    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = service.acquire(photo_result())
    second = service.acquire(photo_result())

    assert first.created_asset is True
    assert second.asset_id == first.asset_id
    assert second.duplicate_reason == "provider_asset"
    assert requests == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        assert session.scalar(select(func.count()).select_from(MediaSource)) == 1
        history = list(session.scalars(select(MediaDownload).order_by(MediaDownload.id)))
        assert [item.status for item in history] == ["success", "reused"]
        assert history[1].media_asset_id == first.asset_id
        assert history[1].download_url is None
        assert history[1].downloaded_bytes == 0
        assert history[1].http_status_code is None
        assert history[1].request_metadata == {
            "network_transfer": False,
            "reuse_reason": "provider_asset",
            "catalog_source_id": "photo:42",
        }
        assert history[1].completed_at is not None

    skipped = service.find_existing("pexels", "image", "42")
    assert skipped is not None
    assert skipped.duplicate_reason == "provider_asset"
    assert requests == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaDownload)) == 3
        latest = session.scalar(select(MediaDownload).order_by(MediaDownload.id.desc()))
        assert latest is not None
        assert latest.status == "reused"
        assert latest.request_metadata["network_transfer"] is False
    engine.dispose()


def test_duplicate_sha_reuses_asset_and_adds_source(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"Content-Type": "image/jpeg"}, content=b"same bytes"
                )
            )
        ),
    )
    first = service.acquire(photo_result("42"))
    second_result = replace(
        photo_result("43"),
        provider="other-stock",
        source_url="https://other.test/assets/43",
        download_url="https://other.test/assets/43.jpeg",
        license_name="Other License",
        license_url="https://other.test/license",
        attribution_text="Credit Other Creator",
    )
    second = service.acquire(second_result)

    assert second.asset_id == first.asset_id
    assert second.created_asset is False
    assert second.created_source is True
    assert second.duplicate_reason == "sha256"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        assert session.scalar(select(func.count()).select_from(MediaSource)) == 2
        assert session.scalar(select(func.count()).select_from(MediaProvider)) == 2
        assert session.scalar(select(func.count()).select_from(AssetLicense)) == 1
        history = list(session.scalars(select(MediaDownload).order_by(MediaDownload.id)))
        assert [item.status for item in history] == ["success", "duplicate"]
        assert history[1].media_asset_id == first.asset_id
        assert history[1].downloaded_bytes == len(b"same bytes")
        assert history[1].http_status_code == 200
        assert history[1].request_metadata == {
            "network_transfer": True,
            "reuse_reason": "sha256",
            "source_attached": True,
        }
        asset = session.get(MediaAsset, first.asset_id)
        assert asset is not None
        assert asset.license is not None
        assert asset.license.license_name == "Pexels License"
    files = [path for path in (catalog_settings.root / "Library/Images").iterdir() if path.is_file()]
    assert len(files) == 1
    engine.dispose()


def test_failed_download_history_has_no_asset_relationship(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    503, headers={"Content-Type": "text/plain"}, content=b"unavailable"
                )
            )
        ),
    )

    with pytest.raises(MediaDownloadError, match="HTTP 503"):
        service.acquire(photo_result("503"))

    with Session(engine) as session:
        history = session.scalar(select(MediaDownload))
        assert history is not None
        assert history.status == "failed"
        assert history.provider_asset_id == "503"
        assert history.attempted_at is not None
        assert history.completed_at is not None
        assert history.completed_at >= history.attempted_at
        assert history.media_asset_id is None
        assert history.asset is None
        assert history.relative_path is None
        assert history.sha256 is None
        assert history.downloaded_bytes == 0
        assert history.http_status_code == 503
        assert history.content_type == "text/plain"
        assert history.error_category == "http"
        assert history.error_message == "Media download returned HTTP 503"
        assert history.request_metadata == {
            "network_transfer": True,
            "failure_stage": "transfer",
        }
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0
    engine.dispose()


def test_video_ffprobe_metadata_overrides_provider_values(catalog_settings: Settings) -> None:
    result = MediaSearchResult(
        provider="pexels",
        provider_asset_id="99",
        media_type="video",
        title=None,
        description=None,
        creator_name="Videographer",
        creator_url=None,
        source_url="https://www.pexels.com/video/99/",
        download_url="https://videos.pexels.test/99.mp4",
        preview_url=None,
        width=640,
        height=360,
        duration_ms=1_000,
        mime_type="video/mp4",
        license_name="Pexels License",
        license_url="https://www.pexels.com/legal-pages/license/",
        attribution_required=False,
        attribution_text="Video by Videographer on Pexels",
        raw_metadata={"id": 99},
    )
    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"Content-Type": "video/mp4"}, content=b"fake-video"
                )
            )
        ),
        metadata_probe=lambda path: ProbeResult(
            width=1920, height=1080, duration_ms=12_500, raw_metadata={"format": {}}
        ),
    )
    outcome = service.acquire(result)
    with Session(engine) as session:
        asset = session.get(MediaAsset, outcome.asset_id)
        assert asset is not None
        assert (asset.width, asset.height, asset.duration_ms) == (1920, 1080, 12_500)
        assert asset.relative_path.startswith("Library/Videos/")
        assert asset.technical_metadata["download"]["ffprobe"] == {"format": {}}
    engine.dispose()
