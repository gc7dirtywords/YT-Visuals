from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import unicodedata
import warnings
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombWarning
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import (
    AssetLicense,
    MediaAsset,
    MediaDownload,
    MediaLocation,
    MediaProvider,
    MediaSource,
)
from .providers.base import MediaSearchResult
from .providers.errors import MediaDownloadError


SENSITIVE_METADATA_KEYS = {
    "api-key",
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "password",
    "proxy-authorization",
    "refresh_token",
    "secret",
    "token",
}

PEXELS_DOWNLOAD_HOSTS = frozenset(
    {"images.pexels.com", "videos.pexels.com", "player.vimeo.com"}
)
PEXELS_MEDIA_USER_AGENT = "YT-ChannelOps"
YT_VISUALS_USER_AGENT = "YT-Visuals/0.1 (https://github.com/gc7dirtywords/YT-Visuals)"
IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
VIDEO_MIME_TYPES = frozenset(
    {"video/mp4", "video/webm", "video/quicktime", "video/x-m4v", "video/x-matroska"}
)
AUDIO_MIME_TYPES = frozenset(
    {
        "audio/wav", "audio/wave", "audio/x-wav", "audio/x-pn-wav",
        "audio/vnd.wave", "audio/mpeg", "audio/mp3", "audio/flac", "audio/x-flac",
    }
)
PEXELS_POLICY_REVIEWED_AT = datetime(2026, 8, 25, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    container: str | None = None
    raw_metadata: dict[str, Any] | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    asset_id: int
    relative_path: str
    sha256: str
    file_size_bytes: int
    created_asset: bool
    created_source: bool
    duplicate_reason: str | None = None
    download_history_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    temporary_path: Path
    sha256: str
    file_size_bytes: int
    http_status_code: int
    content_type: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionContext:
    workflow_id: str | None = None
    package_id: str | None = None
    beat_id: str | None = None
    directive_index: int | None = None
    provider_rank: int | None = None
    executable_query: str | None = None
    required_terms: tuple[str, ...] = ()
    directive_media_type: str | None = None

    def to_metadata(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in asdict(self).items()
            if value not in (None, (), [])
        }


@dataclass(frozen=True, slots=True)
class ObservedMedia:
    mime_type: str
    width: int | None
    height: int | None
    duration_ms: int | None = None
    probe_metadata: dict[str, Any] | None = None
    audio_codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    container: str | None = None


class _TransferFailure(MediaDownloadError):
    def __init__(
        self,
        category: str,
        message: str,
        *,
        http_status_code: int | None = None,
        content_type: str | None = None,
        downloaded_bytes: int | None = None,
        sha256: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.http_status_code = http_status_code
        self.content_type = content_type
        self.downloaded_bytes = downloaded_bytes
        self.sha256 = sha256


MetadataProbe = Callable[[Path], ProbeResult]


def probe_media_file(path: Path) -> ProbeResult:
    executable = shutil.which("ffprobe")
    if executable is None:
        return ProbeResult(warning="ffprobe was not found on PATH")
    try:
        completed = subprocess.run(
            [
                executable,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ProbeResult(warning=f"ffprobe failed: {exc}")
    if completed.returncode != 0:
        detail = completed.stderr.strip().replace("\n", " ")[:240]
        return ProbeResult(warning=f"ffprobe returned {completed.returncode}: {detail}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return ProbeResult(warning="ffprobe returned malformed JSON")
    if not isinstance(payload, dict):
        return ProbeResult(warning="ffprobe returned an unexpected document")

    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"),
        {},
    )
    audio_stream = next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"),
        {},
    )
    width = _positive_int(video_stream.get("width"))
    height = _positive_int(video_stream.get("height"))
    duration = video_stream.get("duration")
    if duration is None and isinstance(payload.get("format"), dict):
        duration = payload["format"].get("duration")
    return ProbeResult(
        width=width,
        height=height,
        duration_ms=_duration_ms(duration),
        audio_codec=audio_stream.get("codec_name") if isinstance(audio_stream.get("codec_name"), str) else None,
        sample_rate=_positive_int_from_string(audio_stream.get("sample_rate")),
        channels=_positive_int(audio_stream.get("channels")),
        container=(payload.get("format") or {}).get("format_name") if isinstance(payload.get("format"), dict) else None,
        raw_metadata=payload,
    )


def safe_filename(result: MediaSearchResult, mime_type: str | None, sha256: str) -> str:
    kind = {"image": "photo", "video": "video", "audio": "sfx"}[result.media_type]
    label = result.title or result.creator_name or kind
    normalized = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()[:60] or "asset"
    provider = re.sub(r"[^a-zA-Z0-9]+", "-", result.provider).strip("-").lower() or "provider"
    asset_id = re.sub(r"[^a-zA-Z0-9]+", "-", result.provider_asset_id).strip("-") or "unknown"
    extension = _extension_for(mime_type, result.download_url)
    return f"{provider}-{kind}-{asset_id}-{slug}-{sha256[:10]}{extension}"


class AcquisitionService:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        *,
        http_client: httpx.Client | None = None,
        metadata_probe: MetadataProbe = probe_media_file,
        timeout_seconds: float = 30.0,
        allowed_download_hosts: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.metadata_probe = metadata_probe
        self.timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0))
        self.allowed_download_hosts = frozenset(
            host.casefold() for host in (allowed_download_hosts or PEXELS_DOWNLOAD_HOSTS)
        )
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(
            follow_redirects=True,
            headers={"User-Agent": YT_VISUALS_USER_AGENT},
        )

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def recover_incomplete(self) -> int:
        """Recover only files named by durable, incomplete acquisition journals."""
        with Session(self.engine) as session:
            history_ids = list(
                session.scalars(
                    select(MediaDownload.id).where(MediaDownload.status == "started")
                )
            )
        recovered = 0
        for history_id in history_ids:
            if self._recover_one(history_id):
                recovered += 1
        return recovered

    def _recover_one(self, history_id: int) -> bool:
        with Session(self.engine) as session:
            history = session.get(MediaDownload, history_id)
            if history is None or history.status != "started":
                return False
            metadata = history.request_metadata if isinstance(history.request_metadata, dict) else {}
            if metadata.get("stage") != "validated":
                partial = self.settings.temp_root / "acquisitions" / str(history_id) / "download.part"
                partial.unlink(missing_ok=True)
                _remove_empty_parents(partial.parent, self.settings.temp_root)
                history.status = "failed"
                history.completed_at = _utcnow()
                history.error_category = "interrupted"
                history.error_message = "Interrupted before media validation completed"
                session.commit()
                return False
            try:
                staging = self._temp_path(metadata["staging_relative_path"])
                destination = self._library_path(metadata["intended_relative_path"])
                allowed_parent = self.settings.library_root / _library_directory(history.media_type)
                destination.resolve(strict=False).relative_to(allowed_parent.resolve())
                if not destination.is_file() and staging.is_file():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staging, destination)
                if not destination.is_file():
                    raise MediaDownloadError("No validated media file survived the interrupted acquisition")
                actual_sha, actual_size = _file_sha256(destination)
                if actual_sha != history.sha256 or actual_size != history.downloaded_bytes:
                    raise MediaDownloadError("Recovered media does not match its durable journal")
                result = MediaSearchResult(**metadata["normalized_result"])
                observed = ObservedMedia(**metadata["observed_media"])
                asset = session.scalar(select(MediaAsset).where(MediaAsset.sha256 == actual_sha))
                now = _utcnow()
                relative = self._library_relative_path(destination)
                stat = destination.stat()
                if asset is None:
                    asset = MediaAsset(
                        relative_path=relative, media_type=result.media_type, title=result.title,
                        description=result.description, mime_type=observed.mime_type,
                        file_size_bytes=actual_size, sha256=actual_sha, width=observed.width,
                        height=observed.height, duration_ms=observed.duration_ms,
                        file_modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        last_verified_at=now,
                        technical_metadata={
                            "provider": _sanitize_metadata(result.raw_metadata),
                            "download": {"content_type": history.content_type, "ffprobe": observed.probe_metadata},
                            "provider_acquisition": _provider_acquisition_metadata(
                                _context_from_metadata(metadata.get("selection"))
                            ),
                        },
                    )
                    session.add(asset)
                    session.flush()
                if not any(item.relative_path == relative for item in asset.locations):
                    session.add(MediaLocation(
                        asset=asset, relative_path=relative, status="available",
                        provenance_type="provider_download", file_size_bytes=actual_size,
                        file_modified_ns=stat.st_mtime_ns,
                        file_modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        first_seen_at=now, last_seen_at=now,
                    ))
                asset.status = "active"
                self._attach_source(session, asset, result)
                self._attach_license_if_missing(asset, result)
                self._merge_search_provenance(asset, _context_from_metadata(metadata.get("selection")))
                downloaded = DownloadedFile(
                    destination, actual_sha, actual_size,
                    history.http_status_code or 200, history.content_type,
                )
                self._complete_history(
                    history, status="success", asset=asset, downloaded=downloaded,
                    request_metadata={"network_transfer": True, "recovered": True},
                )
                session.commit()
                _remove_empty_parents(staging.parent, self.settings.temp_root)
                return True
            except Exception as exc:
                session.rollback()
                self._mark_failed(history_id, exc)
                return False

    def acquire(
        self, result: MediaSearchResult, *, context: AcquisitionContext | None = None
    ) -> AcquisitionOutcome:
        existing = self._existing_provider_asset(result)
        if existing is not None:
            return existing

        history_id = self._begin_history(result, context)
        try:
            downloaded = self._download(result, history_id)
            observed = self._validate_media(downloaded, result)
        except Exception as exc:
            self._mark_failed(history_id, exc)
            if "downloaded" in locals():
                downloaded.temporary_path.unlink(missing_ok=True)
                _remove_empty_parents(
                    downloaded.temporary_path.parent, self.settings.temp_root
                )
            raise

        destination: Path | None = None
        try:
            with Session(self.engine) as session:
                history = session.get(MediaDownload, history_id)
                if history is None or history.status != "started":
                    raise RuntimeError(f"Download history {history_id} is not open")

                known_source = self._find_source(
                    session, result.provider, result.catalog_source_id
                )
                if (
                    known_source is not None
                    and known_source.asset.sha256
                    and known_source.asset.sha256 != downloaded.sha256
                ):
                    raise MediaDownloadError(
                        "Provider asset bytes changed from the cataloged SHA-256"
                    )

                duplicate_asset = session.scalar(
                    select(MediaAsset).where(MediaAsset.sha256 == downloaded.sha256)
                )
                if duplicate_asset is not None:
                    created_source = self._attach_source(session, duplicate_asset, result)
                    self._attach_license_if_missing(duplicate_asset, result)
                    restored = False
                    if not self._asset_file_available(duplicate_asset):
                        self._restore_asset_file(
                            session,
                            history,
                            duplicate_asset,
                            result,
                            downloaded,
                            observed,
                            context,
                        )
                        restored = True
                    self._merge_search_provenance(duplicate_asset, context)
                    self._complete_history(
                        history,
                        status="success" if restored else "duplicate",
                        asset=duplicate_asset,
                        downloaded=downloaded,
                        request_metadata={
                            "network_transfer": True,
                            "reuse_reason": "sha256",
                            "source_attached": created_source,
                            "restored_missing_asset": restored,
                        },
                    )
                    session.commit()
                    return AcquisitionOutcome(
                        asset_id=duplicate_asset.id,
                        relative_path=duplicate_asset.relative_path,
                        sha256=duplicate_asset.sha256 or downloaded.sha256,
                        file_size_bytes=duplicate_asset.file_size_bytes or downloaded.file_size_bytes,
                        created_asset=False,
                        created_source=created_source,
                        duplicate_reason="provider_asset" if known_source else "sha256",
                        download_history_id=history_id,
                    )

                mime_type = observed.mime_type
                destination = self._destination_path(
                    result, safe_filename(result, mime_type, downloaded.sha256)
                )
                self._record_validated_transfer(
                    session,
                    history,
                    result,
                    downloaded,
                    observed,
                    destination,
                    context,
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(downloaded.temporary_path, destination)

                relative_path = self._library_relative_path(destination)
                destination_stat = destination.stat()
                observed_at = _utcnow()
                asset = MediaAsset(
                    relative_path=relative_path,
                    media_type=result.media_type,
                    title=result.title,
                    description=result.description,
                    mime_type=mime_type,
                    file_size_bytes=downloaded.file_size_bytes,
                    sha256=downloaded.sha256,
                    width=observed.width,
                    height=observed.height,
                    duration_ms=observed.duration_ms,
                    file_modified_at=datetime.fromtimestamp(destination_stat.st_mtime, tz=timezone.utc),
                    last_verified_at=observed_at,
                    technical_metadata={
                        "provider": _sanitize_metadata(result.raw_metadata),
                        "download": {
                            "content_type": downloaded.content_type,
                            "ffprobe": observed.probe_metadata,
                        },
                        "provider_acquisition": _provider_acquisition_metadata(context),
                    },
                )
                session.add(asset)
                session.flush()
                session.add(
                    MediaLocation(
                        asset=asset,
                        relative_path=relative_path,
                        status="available",
                        provenance_type="provider_download",
                        file_size_bytes=destination_stat.st_size,
                        file_modified_ns=destination_stat.st_mtime_ns,
                        file_modified_at=datetime.fromtimestamp(
                            destination_stat.st_mtime, tz=timezone.utc
                        ),
                        first_seen_at=observed_at,
                        last_seen_at=observed_at,
                    )
                )
                self._attach_source(session, asset, result)
                self._attach_license_if_missing(asset, result)
                self._complete_history(
                    history,
                    status="success",
                    asset=asset,
                    downloaded=downloaded,
                    request_metadata={"network_transfer": True, "source_attached": True},
                )
                session.commit()
                return AcquisitionOutcome(
                    asset_id=asset.id,
                    relative_path=asset.relative_path,
                    sha256=asset.sha256 or downloaded.sha256,
                    file_size_bytes=asset.file_size_bytes or downloaded.file_size_bytes,
                    created_asset=True,
                    created_source=True,
                    download_history_id=history_id,
                )
        except Exception as exc:
            if not self._validated_file_survives(history_id):
                self._mark_failed(history_id, exc, downloaded=downloaded)
            raise
        finally:
            downloaded.temporary_path.unlink(missing_ok=True)
            _remove_empty_parents(downloaded.temporary_path.parent, self.settings.temp_root)

    def _validated_file_survives(self, history_id: int) -> bool:
        try:
            with Session(self.engine) as session:
                history = session.get(MediaDownload, history_id)
                metadata = history.request_metadata if history else None
                if not isinstance(metadata, dict) or metadata.get("stage") != "validated":
                    return False
                destination = self._library_path(str(metadata.get("intended_relative_path", "")))
                return destination.is_file()
        except Exception:
            return False

    def lookup_existing(
        self, provider: str, media_type: str, provider_asset_id: str
    ) -> AcquisitionOutcome | None:
        catalog_source_id = _catalog_source_id(media_type, provider_asset_id)
        with Session(self.engine) as session:
            source = self._find_source(session, provider, catalog_source_id)
            if source is None:
                return None
            return self._outcome_for_existing_source(source, None)

    def find_existing(
        self, provider: str, media_type: str, provider_asset_id: str
    ) -> AcquisitionOutcome | None:
        catalog_source_id = _catalog_source_id(media_type, provider_asset_id)
        with Session(self.engine) as session:
            source = self._find_source(session, provider, catalog_source_id)
            if source is None:
                return None
            history_id = self._record_reuse(
                session,
                source,
                provider=provider,
                provider_asset_id=provider_asset_id,
                media_type=media_type,
                source_url=source.source_url,
                provider_metadata=None,
            )
            session.commit()
            return self._outcome_for_existing_source(source, history_id)

    def _existing_provider_asset(self, result: MediaSearchResult) -> AcquisitionOutcome | None:
        with Session(self.engine) as session:
            source = self._find_source(session, result.provider, result.catalog_source_id)
            if source is None:
                return None
            if not self._source_file_available(source):
                return None
            history_id = self._record_reuse(
                session,
                source,
                provider=result.provider,
                provider_asset_id=result.provider_asset_id,
                media_type=result.media_type,
                source_url=result.source_url,
                provider_metadata=result.raw_metadata,
            )
            session.commit()
            return self._outcome_for_existing_source(source, history_id)

    @staticmethod
    def _find_source(
        session: Session, provider: str, catalog_source_id: str
    ) -> MediaSource | None:
        return session.scalar(
            select(MediaSource)
            .join(MediaProvider)
            .where(
                func.lower(MediaProvider.name) == provider.lower(),
                MediaSource.provider_asset_id == catalog_source_id,
            )
        )

    @staticmethod
    def _outcome_for_existing_source(
        source: MediaSource, history_id: int | None
    ) -> AcquisitionOutcome:
        asset = source.asset
        return AcquisitionOutcome(
            asset_id=asset.id,
            relative_path=asset.relative_path,
            sha256=asset.sha256 or "",
            file_size_bytes=asset.file_size_bytes or 0,
            created_asset=False,
            created_source=False,
            duplicate_reason="provider_asset",
            download_history_id=history_id,
        )

    def _source_file_available(self, source: MediaSource) -> bool:
        return self._asset_file_available(source.asset)

    def _asset_file_available(self, asset: MediaAsset) -> bool:
        for location in asset.locations:
            if location.status != "available":
                continue
            try:
                path = self._library_path(location.relative_path)
            except MediaDownloadError:
                continue
            if path.is_file():
                return True
        if not asset.locations and asset.status == "active":
            try:
                return self._library_path(asset.relative_path).is_file()
            except MediaDownloadError:
                return False
        return False

    def _record_validated_transfer(
        self,
        session: Session,
        history: MediaDownload,
        result: MediaSearchResult,
        downloaded: DownloadedFile,
        observed: ObservedMedia,
        destination: Path,
        context: AcquisitionContext | None,
    ) -> None:
        relative = self._library_relative_path(destination)
        if history.status != "started":
            raise MediaDownloadError("Download history is not available for finalization")
        history.relative_path = relative
        history.sha256 = downloaded.sha256
        history.downloaded_bytes = downloaded.file_size_bytes
        history.http_status_code = downloaded.http_status_code
        history.content_type = downloaded.content_type
        history.request_metadata = {
            "network_transfer": True,
            "stage": "validated",
            "selection": context.to_metadata() if context else {},
            "normalized_result": _sanitize_metadata(result.to_dict()),
            "observed_media": asdict(observed),
            "staging_relative_path": self._temp_relative_path(downloaded.temporary_path),
            "intended_relative_path": relative,
        }
        session.commit()

    def _restore_asset_file(
        self,
        session: Session,
        history: MediaDownload,
        asset: MediaAsset,
        result: MediaSearchResult,
        downloaded: DownloadedFile,
        observed: ObservedMedia,
        context: AcquisitionContext | None,
    ) -> None:
        destination = self._destination_path(
            result, safe_filename(result, observed.mime_type, downloaded.sha256)
        )
        self._record_validated_transfer(
            session, history, result, downloaded, observed, destination, context
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(downloaded.temporary_path, destination)
        stat = destination.stat()
        now = _utcnow()
        relative = self._library_relative_path(destination)
        asset.relative_path = relative
        asset.status = "active"
        asset.mime_type = observed.mime_type
        asset.file_size_bytes = downloaded.file_size_bytes
        asset.sha256 = downloaded.sha256
        asset.width = observed.width
        asset.height = observed.height
        asset.duration_ms = observed.duration_ms
        asset.file_modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        asset.last_verified_at = now
        existing_location = next(
            (item for item in asset.locations if item.relative_path == relative), None
        )
        if existing_location is None:
            session.add(MediaLocation(
                asset=asset,
                relative_path=relative,
                status="available",
                provenance_type="provider_download",
                file_size_bytes=stat.st_size,
                file_modified_ns=stat.st_mtime_ns,
                file_modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                first_seen_at=now,
                last_seen_at=now,
            ))
        else:
            existing_location.status = "available"
            existing_location.provenance_type = "provider_download"
            existing_location.file_size_bytes = stat.st_size
            existing_location.file_modified_ns = stat.st_mtime_ns
            existing_location.file_modified_at = datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            )
            existing_location.last_seen_at = now
            existing_location.missing_since = None

    @staticmethod
    def _merge_search_provenance(
        asset: MediaAsset, context: AcquisitionContext | None
    ) -> None:
        provenance = _search_provenance(context)
        if not provenance:
            return
        metadata = dict(asset.technical_metadata or {})
        existing = metadata.get("provider_acquisition")
        entries = list(existing.get("searches", [])) if isinstance(existing, dict) else []
        if provenance not in entries:
            entries.append(provenance)
        metadata["provider_acquisition"] = {"searches": entries}
        asset.technical_metadata = metadata

    def _begin_history(
        self, result: MediaSearchResult, context: AcquisitionContext | None
    ) -> int:
        with Session(self.engine) as session:
            history = MediaDownload(
                provider=result.provider,
                provider_asset_id=result.provider_asset_id,
                media_type=result.media_type,
                source_url=result.source_url,
                download_url=result.download_url,
                attempted_at=_utcnow(),
                status="started",
                provider_metadata=_sanitize_metadata(result.raw_metadata),
                request_metadata={
                    "network_transfer": True,
                    "stage": "started",
                    "selection": context.to_metadata() if context else {},
                },
            )
            session.add(history)
            session.commit()
            return history.id

    @staticmethod
    def _record_reuse(
        session: Session,
        source: MediaSource,
        *,
        provider: str,
        provider_asset_id: str,
        media_type: str,
        source_url: str | None,
        provider_metadata: dict[str, Any] | None,
    ) -> int:
        now = _utcnow()
        asset = source.asset
        history = MediaDownload(
            provider=provider,
            provider_asset_id=provider_asset_id,
            media_type=media_type,
            source_url=source_url,
            download_url=None,
            attempted_at=now,
            completed_at=now,
            status="reused",
            asset=asset,
            relative_path=asset.relative_path,
            sha256=asset.sha256,
            downloaded_bytes=0,
            provider_metadata=_sanitize_metadata(provider_metadata),
            request_metadata={
                "network_transfer": False,
                "reuse_reason": "provider_asset",
                "catalog_source_id": source.provider_asset_id,
            },
        )
        session.add(history)
        session.flush()
        return history.id

    @staticmethod
    def _complete_history(
        history: MediaDownload,
        *,
        status: str,
        asset: MediaAsset,
        downloaded: DownloadedFile,
        request_metadata: dict[str, Any],
    ) -> None:
        history.completed_at = _utcnow()
        history.status = status
        history.asset = asset
        history.relative_path = asset.relative_path
        history.sha256 = downloaded.sha256
        history.downloaded_bytes = downloaded.file_size_bytes
        history.http_status_code = downloaded.http_status_code
        history.content_type = downloaded.content_type
        history.request_metadata = request_metadata

    def _mark_failed(
        self,
        history_id: int,
        error: Exception,
        *,
        downloaded: DownloadedFile | None = None,
    ) -> None:
        try:
            with Session(self.engine) as session:
                history = session.get(MediaDownload, history_id)
                if history is None or history.status != "started":
                    return
                history.completed_at = _utcnow()
                history.status = "failed"
                history.error_category = getattr(error, "category", type(error).__name__)[:100]
                history.error_message = _redact_text(str(error))[:1000]
                history.http_status_code = getattr(error, "http_status_code", None)
                history.content_type = getattr(error, "content_type", None)
                history.downloaded_bytes = getattr(error, "downloaded_bytes", None)
                history.sha256 = getattr(error, "sha256", None)
                if downloaded is not None:
                    history.http_status_code = downloaded.http_status_code
                    history.content_type = downloaded.content_type
                    history.downloaded_bytes = downloaded.file_size_bytes
                    history.sha256 = downloaded.sha256
                prior_metadata = history.request_metadata or {}
                history.request_metadata = {
                    "network_transfer": True,
                    "failure_stage": "transfer" if isinstance(error, _TransferFailure) else "ingestion",
                    "selection": prior_metadata.get("selection", {}),
                }
                session.commit()
        except Exception:
            # Preserve the original acquisition exception if audit finalization itself fails.
            return

    def _download(self, result: MediaSearchResult, history_id: int) -> DownloadedFile:
        self._validate_download_url(result.download_url)
        staging_dir = self.settings.temp_root / "acquisitions" / str(history_id)
        staging_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = staging_dir / "download.part"
        temporary_path.unlink(missing_ok=True)
        handle = temporary_path.open("wb")
        digest = hashlib.sha256()
        byte_count = 0
        content_type: str | None = None
        http_status_code: int | None = None
        limit = {
            "image": self.settings.max_image_download_bytes,
            "video": self.settings.max_video_download_bytes,
            "audio": self.settings.max_audio_download_bytes,
        }[result.media_type]
        try:
            with handle:
                try:
                    request = self._download_request(result.download_url, result.provider)
                    with closing(self.http_client.send(request, stream=True, auth=None, follow_redirects=True)) as response:
                        http_status_code = response.status_code
                        content_type = response.headers.get("Content-Type")
                        self._validate_download_url(str(response.url))
                        if not 200 <= response.status_code < 300:
                            raise _TransferFailure(
                                "http",
                                f"Media download returned HTTP {response.status_code}",
                                http_status_code=response.status_code,
                                content_type=content_type,
                                downloaded_bytes=0,
                            )
                        content_length = response.headers.get("Content-Length")
                        if content_length is not None:
                            try:
                                declared_length = int(content_length)
                            except ValueError as exc:
                                raise _TransferFailure(
                                    "invalid_content_length",
                                    "Media download returned an invalid Content-Length",
                                    http_status_code=response.status_code,
                                    content_type=content_type,
                                    downloaded_bytes=0,
                                ) from exc
                            if declared_length < 0 or declared_length > limit:
                                raise _TransferFailure(
                                    "too_large",
                                    f"Media download exceeds the configured {limit}-byte limit",
                                    http_status_code=response.status_code,
                                    content_type=content_type,
                                    downloaded_bytes=0,
                                )
                        for chunk in response.iter_bytes(chunk_size=64 * 1024):
                            if not chunk:
                                continue
                            handle.write(chunk)
                            digest.update(chunk)
                            byte_count += len(chunk)
                            if byte_count > limit:
                                raise _TransferFailure(
                                    "too_large",
                                    f"Media download exceeds the configured {limit}-byte limit",
                                    http_status_code=response.status_code,
                                    content_type=content_type,
                                    downloaded_bytes=byte_count,
                                    sha256=digest.hexdigest(),
                                )
                    handle.flush()
                    os.fsync(handle.fileno())
                except httpx.TimeoutException as exc:
                    raise _TransferFailure(
                        "timeout",
                        "Media download timed out",
                        http_status_code=http_status_code,
                        content_type=content_type,
                        downloaded_bytes=byte_count,
                        sha256=digest.hexdigest() if byte_count else None,
                    ) from exc
                except httpx.RequestError as exc:
                    raise _TransferFailure(
                        "connection",
                        f"Media download failed: {exc}",
                        http_status_code=http_status_code,
                        content_type=content_type,
                        downloaded_bytes=byte_count,
                        sha256=digest.hexdigest() if byte_count else None,
                    ) from exc
            if byte_count == 0:
                raise _TransferFailure(
                    "empty",
                    "Media download was empty",
                    http_status_code=http_status_code,
                    content_type=content_type,
                    downloaded_bytes=0,
                )
            return DownloadedFile(
                temporary_path=temporary_path,
                sha256=digest.hexdigest(),
                file_size_bytes=byte_count,
                http_status_code=http_status_code or 200,
                content_type=content_type,
            )
        except Exception:
            temporary_path.unlink(missing_ok=True)
            _remove_empty_parents(temporary_path.parent, self.settings.temp_root)
            raise

    def _download_request(self, url: str, provider: str) -> httpx.Request:
        headers: dict[str, str] | None = None
        if provider.casefold() == "pexels" and _is_pexels_cdn_url(url):
            headers = {"User-Agent": PEXELS_MEDIA_USER_AGENT}
        request = self.http_client.build_request("GET", url, headers=headers, timeout=self.timeout)
        if headers is not None:
            request.headers.pop("Authorization", None)
        return request

    def _library_relative_path(self, path: Path) -> str:
        return f"Library/{path.resolve(strict=False).relative_to(self.settings.library_root.resolve()).as_posix()}"

    def _library_path(self, relative_path: str) -> Path:
        return _storage_path(self.settings.library_root, "Library", relative_path)

    def _temp_relative_path(self, path: Path) -> str:
        return f"Temp/{path.resolve(strict=False).relative_to(self.settings.temp_root.resolve()).as_posix()}"

    def _temp_path(self, relative_path: str) -> Path:
        return _storage_path(self.settings.temp_root, "Temp", relative_path)

    def _validate_download_url(self, url: str) -> None:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme.casefold() != "https" or not host:
            raise _TransferFailure("unsafe_url", "Provider media URL must use HTTPS")
        if not any(host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_download_hosts):
            raise _TransferFailure("unsafe_host", "Provider media URL host is not allowlisted")

    def _validate_media(
        self, downloaded: DownloadedFile, result: MediaSearchResult
    ) -> ObservedMedia:
        declared = self._effective_mime_type(downloaded.content_type, result.mime_type)
        if result.media_type == "image":
            if declared not in IMAGE_MIME_TYPES:
                raise _TransferFailure(
                    "mime_mismatch",
                    "Downloaded response is not an approved image MIME type",
                    http_status_code=downloaded.http_status_code,
                    content_type=downloaded.content_type,
                    downloaded_bytes=downloaded.file_size_bytes,
                    sha256=downloaded.sha256,
                )
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", DecompressionBombWarning)
                    with Image.open(downloaded.temporary_path) as image:
                        image.verify()
                    with Image.open(downloaded.temporary_path) as image:
                        image.load()
                        width, height = image.size
                        observed_mime = Image.MIME.get(image.format or "")
            except (OSError, UnidentifiedImageError, DecompressionBombWarning) as exc:
                raise _TransferFailure(
                    "invalid_image",
                    "Downloaded image could not be decoded safely",
                    http_status_code=downloaded.http_status_code,
                    content_type=downloaded.content_type,
                    downloaded_bytes=downloaded.file_size_bytes,
                    sha256=downloaded.sha256,
                ) from exc
            if observed_mime not in IMAGE_MIME_TYPES or width <= 0 or height <= 0:
                raise _TransferFailure("invalid_image", "Downloaded image metadata is invalid")
            if declared != observed_mime:
                raise _TransferFailure("mime_mismatch", "Downloaded image MIME does not match its bytes")
            return ObservedMedia(observed_mime, width, height)

        if result.media_type == "audio":
            if declared not in AUDIO_MIME_TYPES:
                raise _TransferFailure(
                    "mime_mismatch",
                    "Downloaded response is not an approved audio MIME type",
                    http_status_code=downloaded.http_status_code,
                    content_type=downloaded.content_type,
                    downloaded_bytes=downloaded.file_size_bytes,
                    sha256=downloaded.sha256,
                )
            probe = self.metadata_probe(downloaded.temporary_path)
            if (
                probe.warning
                or not probe.audio_codec
                or probe.duration_ms is None
                or probe.duration_ms <= 0
                or probe.sample_rate is None
                or probe.channels is None
            ):
                raise _TransferFailure(
                    "invalid_audio",
                    "Downloaded audio could not be probed as usable media",
                    http_status_code=downloaded.http_status_code,
                    content_type=downloaded.content_type,
                    downloaded_bytes=downloaded.file_size_bytes,
                    sha256=downloaded.sha256,
                )
            return ObservedMedia(
                declared, None, None, probe.duration_ms, probe.raw_metadata,
                probe.audio_codec, probe.sample_rate, probe.channels, probe.container,
            )

        if declared not in VIDEO_MIME_TYPES:
            raise _TransferFailure(
                "mime_mismatch",
                "Downloaded response is not an approved video MIME type",
                http_status_code=downloaded.http_status_code,
                content_type=downloaded.content_type,
                downloaded_bytes=downloaded.file_size_bytes,
                sha256=downloaded.sha256,
            )
        probe = self.metadata_probe(downloaded.temporary_path)
        if (
            probe.warning
            or probe.width is None
            or probe.height is None
            or probe.duration_ms is None
            or probe.width <= 0
            or probe.height <= 0
            or probe.duration_ms <= 0
        ):
            raise _TransferFailure(
                "invalid_video",
                "Downloaded video could not be probed as usable media",
                http_status_code=downloaded.http_status_code,
                content_type=downloaded.content_type,
                downloaded_bytes=downloaded.file_size_bytes,
                sha256=downloaded.sha256,
            )
        return ObservedMedia(
            declared,
            probe.width,
            probe.height,
            probe.duration_ms,
            probe.raw_metadata,
        )

    def _attach_source(
        self, session: Session, asset: MediaAsset, result: MediaSearchResult
    ) -> bool:
        provider = session.scalar(
            select(MediaProvider).where(func.lower(MediaProvider.name) == result.provider.lower())
        )
        if provider is None:
            provider = MediaProvider(
                name=result.provider,
                website_url="https://www.pexels.com/" if result.provider == "pexels" else None,
            )
            session.add(provider)
            session.flush()
        existing = session.scalar(
            select(MediaSource).where(
                MediaSource.provider_id == provider.id,
                MediaSource.provider_asset_id == result.catalog_source_id,
            )
        )
        if existing is not None:
            if not existing.source_url and result.source_url:
                existing.source_url = result.source_url
            if not existing.creator_name and result.creator_name:
                existing.creator_name = result.creator_name
            if not existing.creator_url and result.creator_url:
                existing.creator_url = result.creator_url
            if not existing.original_filename:
                existing.original_filename = _original_filename(result.download_url)
            return False
        session.add(
            MediaSource(
                asset=asset,
                provider=provider,
                provider_asset_id=result.catalog_source_id,
                source_url=result.source_url,
                creator_name=result.creator_name,
                creator_url=result.creator_url,
                original_filename=_original_filename(result.download_url),
                acquired_at=_utcnow(),
            )
        )
        return True

    @staticmethod
    def _attach_license_if_missing(asset: MediaAsset, result: MediaSearchResult) -> None:
        """Attach documentation without replacing stronger metadata already on an asset."""
        reviewed_at = (
            PEXELS_POLICY_REVIEWED_AT if result.provider.casefold() == "pexels" else None
        )
        if asset.license is None:
            asset.license = AssetLicense(
                license_name=result.license_name or None,
                license_url=result.license_url or None,
                attribution_required=result.attribution_required,
                attribution_text=result.attribution_text,
                usage_terms=result.license_notes,
                commercial_use_allowed=result.commercial_use_allowed,
                modifications_allowed=result.modifications_allowed,
                verified_at=reviewed_at,
            )
            return

        license_record = asset.license
        if not license_record.license_name and result.license_name:
            license_record.license_name = result.license_name
        if not license_record.license_url and result.license_url:
            license_record.license_url = result.license_url
        if not license_record.attribution_text and result.attribution_text:
            license_record.attribution_text = result.attribution_text
        if not license_record.usage_terms and result.license_notes:
            license_record.usage_terms = result.license_notes
        if license_record.commercial_use_allowed is None:
            license_record.commercial_use_allowed = result.commercial_use_allowed
        if license_record.modifications_allowed is None:
            license_record.modifications_allowed = result.modifications_allowed
        license_record.attribution_required = (
            license_record.attribution_required or result.attribution_required
        )
        if license_record.verified_at is None and reviewed_at is not None:
            license_record.verified_at = reviewed_at

    def _destination_path(self, result: MediaSearchResult, filename: str) -> Path:
        directory = self.settings.library_root / _library_directory(result.media_type)
        candidate = directory / filename
        counter = 2
        while candidate.exists():
            candidate = directory / f"{Path(filename).stem}-{counter}{Path(filename).suffix}"
            counter += 1
        candidate.resolve(strict=False).relative_to(directory.resolve())
        return candidate

    @staticmethod
    def _effective_mime_type(downloaded: str | None, _provider_value: str | None) -> str | None:
        downloaded = downloaded.split(";", 1)[0].strip().lower() if downloaded else None
        return downloaded


def _catalog_source_id(media_type: str, provider_asset_id: str) -> str:
    kind = {"image": "photo", "video": "video", "audio": "audio"}[media_type]
    return f"{kind}:{provider_asset_id}"


def _sanitize_metadata(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if value is None or isinstance(value, (int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _sanitize_metadata(item)
            for key, item in value.items()
            if str(key).strip().lower() not in SENSITIVE_METADATA_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_metadata(item) for item in value]
    return str(value)


def _redact_text(value: str) -> str:
    value = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", value)
    return re.sub(
        r"(?i)\b(authorization|api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+",
        r"\1=[redacted]",
        value,
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _duration_ms(value: Any) -> int | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return round(seconds * 1000) if seconds >= 0 else None


def _extension_for(mime_type: str | None, url: str) -> str:
    known = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/x-m4v": ".m4v",
        "video/x-matroska": ".mkv",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/wave": ".wav",
        "audio/x-pn-wav": ".wav",
        "audio/vnd.wave": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/flac": ".flac",
        "audio/x-flac": ".flac",
    }
    if mime_type:
        normalized = mime_type.split(";", 1)[0].strip().lower()
        if normalized in known:
            return known[normalized]
        guessed = mimetypes.guess_extension(normalized)
        if guessed and re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", guessed):
            return guessed.lower()
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"


def _original_filename(url: str) -> str | None:
    name = unquote(Path(urlsplit(url).path).name).strip()
    return name[:512] or None


def _is_pexels_cdn_url(url: str) -> bool:
    return (urlsplit(url).hostname or "").casefold() in {
        "images.pexels.com",
        "videos.pexels.com",
    }


def _library_directory(media_type: str) -> str:
    return {"image": "Images", "video": "Videos", "audio": "SFX"}[media_type]


def _positive_int_from_string(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _search_provenance(context: AcquisitionContext | None) -> dict[str, Any]:
    if context is None or not context.executable_query:
        return {}
    return {
        "query": context.executable_query,
        "required_terms": list(context.required_terms),
        "media_type": context.directive_media_type,
        "directive_index": context.directive_index,
    }


def _provider_acquisition_metadata(
    context: AcquisitionContext | None,
) -> dict[str, Any]:
    provenance = _search_provenance(context)
    return {"searches": [provenance]} if provenance else {"searches": []}


def _safe_root_relative(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path.replace("/", "\\"))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise MediaDownloadError("Unsafe catalog-relative path")
    resolved = (root / candidate).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise MediaDownloadError("Catalog path escapes the configured root") from exc
    return resolved


def _storage_path(root: Path, logical_root: str, relative_path: str) -> Path:
    normalized = relative_path.replace("\\", "/")
    prefix = f"{logical_root}/"
    if not normalized.startswith(prefix):
        raise MediaDownloadError(f"Unsafe {logical_root.lower()}-relative path")
    return _safe_root_relative(root, normalized[len(prefix):])


def _remove_empty_parents(path: Path, stop: Path) -> None:
    stop = stop.resolve(strict=False)
    current = path.resolve(strict=False)
    while current != stop:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _context_from_metadata(value: Any) -> AcquisitionContext | None:
    if not isinstance(value, dict):
        return None
    allowed = {field.name for field in AcquisitionContext.__dataclass_fields__.values()}
    normalized = {key: item for key, item in value.items() if key in allowed}
    if isinstance(normalized.get("required_terms"), list):
        normalized["required_terms"] = tuple(normalized["required_terms"])
    try:
        return AcquisitionContext(**normalized)
    except TypeError:
        return None
