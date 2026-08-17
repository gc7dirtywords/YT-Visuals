from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit

import httpx
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import AssetLicense, MediaAsset, MediaDownload, MediaProvider, MediaSource
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


@dataclass(frozen=True, slots=True)
class ProbeResult:
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
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
    width = _positive_int(video_stream.get("width"))
    height = _positive_int(video_stream.get("height"))
    duration = video_stream.get("duration")
    if duration is None and isinstance(payload.get("format"), dict):
        duration = payload["format"].get("duration")
    return ProbeResult(
        width=width,
        height=height,
        duration_ms=_duration_ms(duration),
        raw_metadata=payload,
    )


def safe_filename(result: MediaSearchResult, mime_type: str | None, sha256: str) -> str:
    kind = "photo" if result.media_type == "image" else "video"
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
        timeout_seconds: float = 60.0,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.metadata_probe = metadata_probe
        self.timeout_seconds = timeout_seconds
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(follow_redirects=True)

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def acquire(self, result: MediaSearchResult) -> AcquisitionOutcome:
        existing = self._existing_provider_asset(result)
        if existing is not None:
            return existing

        history_id = self._begin_history(result)
        try:
            downloaded = self._download(result)
        except Exception as exc:
            self._mark_failed(history_id, exc)
            raise

        destination: Path | None = None
        try:
            with Session(self.engine) as session:
                history = session.get(MediaDownload, history_id)
                if history is None or history.status != "started":
                    raise RuntimeError(f"Download history {history_id} is not open")

                duplicate_asset = session.scalar(
                    select(MediaAsset).where(MediaAsset.sha256 == downloaded.sha256)
                )
                if duplicate_asset is not None:
                    created_source = self._attach_source(session, duplicate_asset, result)
                    self._attach_license_if_missing(duplicate_asset, result)
                    self._complete_history(
                        history,
                        status="duplicate",
                        asset=duplicate_asset,
                        downloaded=downloaded,
                        request_metadata={
                            "network_transfer": True,
                            "reuse_reason": "sha256",
                            "source_attached": created_source,
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
                        duplicate_reason="sha256",
                        download_history_id=history_id,
                    )

                probe = self.metadata_probe(downloaded.temporary_path) if result.media_type == "video" else ProbeResult()
                mime_type = self._effective_mime_type(downloaded.content_type, result.mime_type)
                destination = self._destination_path(
                    result, safe_filename(result, mime_type, downloaded.sha256)
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(downloaded.temporary_path, destination)

                relative_path = destination.relative_to(self.settings.root).as_posix()
                asset = MediaAsset(
                    relative_path=relative_path,
                    media_type=result.media_type,
                    title=result.title,
                    description=result.description,
                    mime_type=mime_type,
                    file_size_bytes=downloaded.file_size_bytes,
                    sha256=downloaded.sha256,
                    width=probe.width or result.width,
                    height=probe.height or result.height,
                    duration_ms=probe.duration_ms if probe.duration_ms is not None else result.duration_ms,
                    file_modified_at=datetime.fromtimestamp(destination.stat().st_mtime, tz=timezone.utc),
                    last_verified_at=_utcnow(),
                    technical_metadata={
                        "provider": _sanitize_metadata(result.raw_metadata),
                        "download": {
                            "content_type": downloaded.content_type,
                            "ffprobe": probe.raw_metadata,
                            "ffprobe_warning": probe.warning,
                        },
                    },
                )
                session.add(asset)
                session.flush()
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
            if destination is not None and destination.exists():
                destination.unlink()
            self._mark_failed(history_id, exc, downloaded=downloaded)
            raise
        finally:
            downloaded.temporary_path.unlink(missing_ok=True)

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
        source: MediaSource, history_id: int
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

    def _begin_history(self, result: MediaSearchResult) -> int:
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
                request_metadata={"network_transfer": True},
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
                history.request_metadata = {
                    "network_transfer": True,
                    "failure_stage": "transfer" if isinstance(error, _TransferFailure) else "ingestion",
                }
                session.commit()
        except Exception:
            # Preserve the original acquisition exception if audit finalization itself fails.
            return

    def _download(self, result: MediaSearchResult) -> DownloadedFile:
        self.settings.root.joinpath("Temp").mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="wb", prefix="yt-visuals-", suffix=".part", dir=self.settings.root / "Temp", delete=False
        )
        temporary_path = Path(handle.name)
        digest = hashlib.sha256()
        byte_count = 0
        content_type: str | None = None
        http_status_code: int | None = None
        try:
            with handle:
                try:
                    with self.http_client.stream(
                        "GET", result.download_url, timeout=self.timeout_seconds, follow_redirects=True
                    ) as response:
                        http_status_code = response.status_code
                        content_type = response.headers.get("Content-Type")
                        if response.status_code >= 400:
                            raise _TransferFailure(
                                "http",
                                f"Media download returned HTTP {response.status_code}",
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
            raise

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
        if asset.license is not None:
            return
        asset.license = AssetLicense(
            license_name=result.license_name,
            license_url=result.license_url,
            attribution_required=result.attribution_required,
            attribution_text=result.attribution_text,
            usage_terms=result.license_notes,
            commercial_use_allowed=result.commercial_use_allowed,
            modifications_allowed=result.modifications_allowed,
            verified_at=_utcnow(),
        )

    def _destination_path(self, result: MediaSearchResult, filename: str) -> Path:
        directory = self.settings.root / "Library" / (
            "Images" if result.media_type == "image" else "Videos"
        )
        candidate = directory / filename
        counter = 2
        while candidate.exists():
            candidate = directory / f"{Path(filename).stem}-{counter}{Path(filename).suffix}"
            counter += 1
        return candidate

    @staticmethod
    def _effective_mime_type(downloaded: str | None, provider_value: str | None) -> str | None:
        downloaded = downloaded.split(";", 1)[0].strip().lower() if downloaded else None
        if downloaded and downloaded != "application/octet-stream":
            return downloaded
        return provider_value


def _catalog_source_id(media_type: str, provider_asset_id: str) -> str:
    kind = "photo" if media_type == "image" else "video"
    return f"{kind}:{provider_asset_id}"


def _sanitize_metadata(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
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
        "video/webm": ".webm",
        "video/quicktime": ".mov",
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
