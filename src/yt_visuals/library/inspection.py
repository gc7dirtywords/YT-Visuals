from __future__ import annotations

import hashlib
import mimetypes
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image, UnidentifiedImageError

from ..acquisition import ProbeResult, probe_media_file


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac"}
MIME_OVERRIDES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
}


class MediaInspectionError(RuntimeError):
    """A supported file could not be read or validated."""


@dataclass(frozen=True, slots=True)
class Candidate:
    absolute_path: Path
    relative_path: str
    media_type: str
    extension: str
    file_size_bytes: int
    file_modified_ns: int
    file_modified_at: datetime


@dataclass(frozen=True, slots=True)
class InspectedMedia:
    candidate: Candidate
    sha256: str
    mime_type: str
    width: int | None
    height: int | None
    duration_ms: int | None
    technical_metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DiscoveryError:
    relative_path: str
    category: str
    message: str


def discover_library_files(library_root: Path) -> tuple[list[Candidate], list[DiscoveryError], int]:
    candidates: list[Candidate] = []
    errors: list[DiscoveryError] = []
    skipped_symlinks = 0
    library_roots = (
        (library_root / "Images", "image", IMAGE_EXTENSIONS),
        (library_root / "Videos", "video", VIDEO_EXTENSIONS),
        (library_root / "SFX", "audio", AUDIO_EXTENSIONS),
    )

    for scan_root, media_type, extensions in library_roots:
        scan_root_resolved = scan_root.resolve(strict=False)
        pending = [scan_root]
        while pending:
            directory = pending.pop()
            try:
                entries = list(os.scandir(directory))
            except OSError as exc:
                errors.append(_discovery_error(library_root, directory, exc))
                continue
            for entry in entries:
                path = Path(entry.path)
                try:
                    if entry.is_symlink():
                        skipped_symlinks += 1
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        resolved = path.resolve(strict=False)
                        try:
                            resolved.relative_to(scan_root_resolved)
                        except ValueError:
                            skipped_symlinks += 1
                            continue
                        pending.append(path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    extension = path.suffix.lower()
                    if extension not in extensions:
                        continue
                    stat = entry.stat(follow_symlinks=False)
                    relative_path = f"Library/{path.relative_to(library_root).as_posix()}"
                    candidates.append(
                        Candidate(
                            absolute_path=path,
                            relative_path=relative_path,
                            media_type=media_type,
                            extension=extension,
                            file_size_bytes=stat.st_size,
                            file_modified_ns=stat.st_mtime_ns,
                            file_modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                        )
                    )
                except OSError as exc:
                    errors.append(_discovery_error(library_root, path, exc))
    candidates.sort(key=lambda item: item.relative_path.casefold())
    return candidates, errors, skipped_symlinks


def inspect_media_file(
    candidate: Candidate,
    *,
    video_probe: Callable[[Path], ProbeResult] = probe_media_file,
) -> InspectedMedia:
    try:
        sha256 = _sha256(candidate.absolute_path)
        if candidate.media_type == "image":
            with Image.open(candidate.absolute_path) as image:
                width, height = image.size
                image_format = image.format
                mode = image.mode
                image.verify()
            if width <= 0 or height <= 0:
                raise MediaInspectionError("image dimensions are invalid")
            mime_type = Image.MIME.get(image_format or "") or _mime_for(candidate.extension)
            metadata: dict[str, Any] = {
                "inspection": {"tool": "Pillow", "format": image_format, "mode": mode}
            }
            duration_ms = None
        elif candidate.media_type == "video":
            probe = video_probe(candidate.absolute_path)
            if probe.warning:
                raise MediaInspectionError(probe.warning)
            if probe.width is None or probe.height is None:
                raise MediaInspectionError("ffprobe found no video stream with dimensions")
            width, height = probe.width, probe.height
            duration_ms = probe.duration_ms
            mime_type = _mime_for(candidate.extension)
            metadata = {"inspection": {"tool": "ffprobe", "ffprobe": probe.raw_metadata}}
        else:
            probe = video_probe(candidate.absolute_path)
            if probe.warning:
                raise MediaInspectionError(probe.warning)
            if (
                not probe.audio_codec
                or probe.duration_ms is None
                or probe.duration_ms <= 0
                or probe.sample_rate is None
                or probe.channels is None
            ):
                raise MediaInspectionError("ffprobe found no usable audio stream")
            width = height = None
            duration_ms = probe.duration_ms
            mime_type = _mime_for(candidate.extension)
            metadata = {
                "inspection": {
                    "tool": "ffprobe",
                    "codec": probe.audio_codec,
                    "container": probe.container,
                    "sample_rate": probe.sample_rate,
                    "channels": probe.channels,
                    "ffprobe": probe.raw_metadata,
                }
            }
    except MediaInspectionError:
        raise
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise MediaInspectionError(str(exc) or type(exc).__name__) from exc

    return InspectedMedia(
        candidate=candidate,
        sha256=sha256,
        mime_type=mime_type,
        width=width,
        height=height,
        duration_ms=duration_ms,
        technical_metadata=metadata,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mime_for(extension: str) -> str:
    return MIME_OVERRIDES.get(extension) or mimetypes.types_map.get(extension) or "application/octet-stream"


def _discovery_error(root: Path, path: Path, exc: OSError) -> DiscoveryError:
    try:
        relative_path = path.relative_to(root).as_posix()
    except ValueError:
        relative_path = path.name
    return DiscoveryError(relative_path, type(exc).__name__, str(exc))
