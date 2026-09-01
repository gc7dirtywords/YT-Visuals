from __future__ import annotations

import hashlib
import io
import json
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from yt_visuals.acquisition import (
    AcquisitionContext,
    AcquisitionService,
    PEXELS_MEDIA_USER_AGENT,
    ProbeResult,
    YT_VISUALS_USER_AGENT,
    safe_filename,
)
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.library import LibraryScanner
from yt_visuals.models import (
    AssetLicense,
    MediaAsset,
    MediaDownload,
    MediaLocation,
    MediaProvider,
    MediaSource,
)
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
        download_url=f"https://images.pexels.com/{asset_id}.jpeg",
        preview_url=f"https://images.pexels.com/{asset_id}-preview.jpeg",
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


def jpeg_bytes(size: tuple[int, int] = (64, 36)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, "navy").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_owned_http_client_uses_descriptive_user_agent(catalog_settings: Settings) -> None:
    engine = initialize_database(catalog_settings)
    service = AcquisitionService(catalog_settings, engine)
    assert service.http_client.headers["User-Agent"] == YT_VISUALS_USER_AGENT
    service.close()
    engine.dispose()


def test_pexels_cdn_download_uses_user_agent_without_authorization(
    catalog_settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == PEXELS_MEDIA_USER_AGENT
        assert "Authorization" not in request.headers
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=jpeg_bytes())

    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(
            headers={"Authorization": "secret-that-must-not-reach-the-cdn"},
            transport=httpx.MockTransport(handler),
        ),
    )

    service.acquire(photo_result())

    engine.dispose()


def test_download_timeout_is_recorded_as_clean_transfer_failure(catalog_settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(MediaDownloadError, match="Media download timed out"):
        service.acquire(photo_result("904"))

    with Session(engine) as session:
        history = session.scalar(select(MediaDownload))
        assert history is not None
        assert history.status == "failed"
        assert history.error_category == "timeout"
        assert history.error_message == "Media download timed out"
    engine.dispose()


def test_streamed_download_hash_safe_filename_and_catalog_insertion(
    catalog_settings: Settings,
) -> None:
    content = jpeg_bytes()
    split = len(content) // 3
    chunks = [content[:split], content[split : split * 2], content[split * 2 :]]
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
        assert (asset.width, asset.height) == (64, 36)
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
        assert history.download_url == "https://images.pexels.com/42.jpeg"
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
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=jpeg_bytes())

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
                    200, headers={"Content-Type": "image/jpeg"}, content=jpeg_bytes()
                )
            )
        ),
        allowed_download_hosts={"images.pexels.com", "other.test"},
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
        assert history[1].downloaded_bytes == len(jpeg_bytes())
        assert history[1].http_status_code == 200
        assert history[1].request_metadata == {
            "network_transfer": True,
            "reuse_reason": "sha256",
            "source_attached": True,
            "restored_missing_asset": False,
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
            "selection": {},
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
        download_url="https://videos.pexels.com/99.mp4",
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


def test_local_asset_later_receives_provider_provenance_without_second_asset(
    catalog_settings: Settings,
) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 16), "blue").save(buffer, format="JPEG")
    content = buffer.getvalue()
    local_path = catalog_settings.root / "Library/Images/preexisting.jpg"
    local_path.write_bytes(content)
    engine = initialize_database(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()

    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, headers={"Content-Type": "image/jpeg"}, content=content
                )
            )
        ),
    )
    outcome = service.acquire(photo_result("88"))
    assert outcome.duplicate_reason == "sha256"
    assert outcome.created_source is True
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        assert session.scalar(select(func.count()).select_from(MediaLocation)) == 1
        assert session.scalar(select(func.count()).select_from(MediaSource)) == 1
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert asset.locations[0].provenance_type == "local_import"
        assert asset.sources[0].provider.name == "pexels"
        assert asset.license is not None
        assert asset.license.license_name == "Pexels License"
    assert [path.name for path in (catalog_settings.root / "Library/Images").iterdir()] == [
        "preexisting.jpg"
    ]
    service.close()
    engine.dispose()


@pytest.mark.parametrize(
    ("url", "content_type", "content", "message"),
    [
        ("http://images.pexels.com/unsafe.jpg", "image/jpeg", b"x", "HTTPS"),
        ("https://evil.example/unsafe.jpg", "image/jpeg", b"x", "allowlisted"),
        ("https://images.pexels.com/wrong.jpg", "text/plain", b"x", "MIME"),
        ("https://images.pexels.com/corrupt.jpg", "image/jpeg", b"not-an-image", "decoded"),
    ],
)
def test_acquisition_rejects_unsafe_urls_mime_and_corrupt_images(
    catalog_settings: Settings,
    url: str,
    content_type: str,
    content: bytes,
    message: str,
) -> None:
    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"Content-Type": content_type}, content=content)
        )),
    )
    with pytest.raises(MediaDownloadError, match=message):
        service.acquire(replace(photo_result("901"), download_url=url))
    assert not list((catalog_settings.root / "Temp").rglob("download.part"))
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0
    service.close()
    engine.dispose()


def test_acquisition_enforces_header_and_streaming_limits(
    catalog_settings: Settings, monkeypatch
) -> None:
    monkeypatch.setenv("YT_VISUALS_MAX_IMAGE_DOWNLOAD_BYTES", "100")
    engine = initialize_database(catalog_settings)
    responses = iter([
        httpx.Response(200, headers={"Content-Type": "image/jpeg", "Content-Length": "101"}, content=b""),
        httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=b"x" * 101),
    ])
    service = AcquisitionService(
        catalog_settings,
        engine,
        http_client=httpx.Client(transport=httpx.MockTransport(lambda request: next(responses))),
    )
    with pytest.raises(MediaDownloadError, match="100-byte limit"):
        service.acquire(photo_result("902"))
    with pytest.raises(MediaDownloadError, match="100-byte limit"):
        service.acquire(photo_result("903"))
    assert not list((catalog_settings.root / "Temp").rglob("download.part"))
    service.close()
    engine.dispose()


def test_known_provider_source_with_missing_file_is_restored(
    catalog_settings: Settings,
) -> None:
    content = jpeg_bytes((80, 45))
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(200, headers={"Content-Type": "image/jpeg"}, content=content)

    engine = initialize_database(catalog_settings)
    service = AcquisitionService(
        catalog_settings, engine,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    first = service.acquire(photo_result("904"))
    (catalog_settings.root / first.relative_path).unlink()
    LibraryScanner(catalog_settings, engine).scan()
    restored = service.acquire(photo_result("904"))
    assert restored.asset_id == first.asset_id
    assert restored.created_asset is False
    assert (catalog_settings.root / restored.relative_path).is_file()
    assert requests == 2
    with Session(engine) as session:
        history = session.scalar(select(MediaDownload).order_by(MediaDownload.id.desc()))
        assert history is not None and history.status == "success"
        assert history.request_metadata["restored_missing_asset"] is True
    service.close()
    engine.dispose()


def test_recovery_catalogs_valid_final_file_from_started_journal(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    content = jpeg_bytes((96, 54))
    digest = hashlib.sha256(content).hexdigest()
    destination = catalog_settings.root / "Library/Images/recovered.jpg"
    destination.write_bytes(content)
    result = photo_result("905")
    context = AcquisitionContext(
        workflow_id="workflow-test", package_id="package-test", beat_id="beat-test",
        directive_index=0, provider_rank=1, executable_query="dark fireplace",
        required_terms=("dark",), directive_media_type="image",
    )
    with Session(engine) as session:
        history = MediaDownload(
            provider="pexels", provider_asset_id="905", media_type="image",
            source_url=result.source_url, download_url=result.download_url,
            attempted_at=datetime.now(timezone.utc), status="started",
            relative_path="Library/Images/recovered.jpg", sha256=digest,
            downloaded_bytes=len(content), http_status_code=200,
            content_type="image/jpeg", provider_metadata=result.raw_metadata,
            request_metadata={
                "network_transfer": True, "stage": "validated",
                "selection": context.to_metadata(), "normalized_result": result.to_dict(),
                "observed_media": {
                    "mime_type": "image/jpeg", "width": 96, "height": 54,
                    "duration_ms": None, "probe_metadata": None,
                },
                "staging_relative_path": "Temp/acquisitions/1/download.part",
                "intended_relative_path": "Library/Images/recovered.jpg",
            },
        )
        session.add(history)
        session.commit()
        history_id = history.id
    service = AcquisitionService(catalog_settings, engine)
    assert service.recover_incomplete() == 1
    with Session(engine) as session:
        history = session.get(MediaDownload, history_id)
        asset = session.scalar(select(MediaAsset))
        assert history is not None and history.status == "success"
        assert history.request_metadata == {"network_transfer": True, "recovered": True}
        assert asset is not None and asset.sha256 == digest
        assert asset.technical_metadata["provider_acquisition"]["searches"][0]["query"] == "dark fireplace"
    service.close()
    engine.dispose()


def test_recovery_marks_unvalidated_partial_as_interrupted(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    with Session(engine) as session:
        history = MediaDownload(
            provider="pexels", provider_asset_id="906", media_type="image",
            source_url=photo_result("906").source_url,
            download_url=photo_result("906").download_url,
            attempted_at=datetime.now(timezone.utc), status="started",
            request_metadata={"network_transfer": True, "stage": "started"},
        )
        session.add(history)
        session.commit()
        history_id = history.id
    partial = catalog_settings.root / f"Temp/acquisitions/{history_id}/download.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"partial")
    service = AcquisitionService(catalog_settings, engine)
    assert service.recover_incomplete() == 0
    assert not partial.exists()
    with Session(engine) as session:
        history = session.get(MediaDownload, history_id)
        assert history is not None and history.status == "failed"
        assert history.error_category == "interrupted"
    service.close()
    engine.dispose()
