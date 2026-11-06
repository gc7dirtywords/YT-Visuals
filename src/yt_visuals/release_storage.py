from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from .config import Settings
from .models import VideoRelease


MAX_STORAGE_COMPONENT_LENGTH = 180
EXECUTION_CONFIRMATION = "MOVE_RELEASE_DIRECTORIES"
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ReleaseStorageError(RuntimeError):
    pass


def validate_storage_component(value: str) -> str:
    if not value or value != value.strip() or value in {".", ".."}:
        raise ReleaseStorageError("release storage path is invalid")
    if len(value) > MAX_STORAGE_COMPONENT_LENGTH:
        raise ReleaseStorageError("release storage path is too long")
    if Path(value).is_absolute() or Path(value).name != value:
        raise ReleaseStorageError("release storage path must be one directory name")
    if _FORBIDDEN.search(value) or value.endswith((" ", ".")):
        raise ReleaseStorageError("release storage path is not Windows/SMB safe")
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        raise ReleaseStorageError("release storage path uses a reserved Windows name")
    return value


def storage_component_for_release(release_id: str, storage_path: str | None) -> str:
    return validate_storage_component(storage_path or release_id)


def storage_name_base(release_name: str) -> str:
    value = unicodedata.normalize("NFC", release_name).strip()
    value = _FORBIDDEN.sub(" - ", value)
    value = _WHITESPACE.sub(" ", value).strip(" .")
    if not value:
        value = "Release"
    if value.split(".", 1)[0].upper() in _WINDOWS_RESERVED:
        value = f"Release - {value}"
    value = value[:MAX_STORAGE_COMPONENT_LENGTH].rstrip(" .")
    return validate_storage_component(value)


def choose_storage_component(
    release_name: str, release_id: str, occupied: Iterable[str]
) -> str:
    occupied_folded = {item.casefold() for item in occupied}
    base = storage_name_base(release_name)
    if base.casefold() not in occupied_folded:
        return base
    suffix = f" [{release_id[:8]}]"
    candidate = f"{base[:MAX_STORAGE_COMPONENT_LENGTH - len(suffix)].rstrip(' .')}{suffix}"
    if candidate.casefold() not in occupied_folded:
        return validate_storage_component(candidate)
    suffix = f" [{release_id}]"
    candidate = f"{base[:MAX_STORAGE_COMPONENT_LENGTH - len(suffix)].rstrip(' .')}{suffix}"
    if candidate.casefold() in occupied_folded:
        raise ReleaseStorageError("could not generate a unique release storage path")
    return validate_storage_component(candidate)


@dataclass(frozen=True, slots=True)
class Manifest:
    files: int
    directories: int
    symlinks: int
    bytes: int
    digest: str


def directory_manifest(root: Path) -> Manifest:
    if root.is_symlink() or not root.is_dir():
        raise ReleaseStorageError(f"manifest root is not a real directory: {root}")
    records: list[str] = []
    files = directories = symlinks = total_bytes = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            symlinks += 1
            records.append(f"L\0{relative}\0{os.readlink(path)}")
        elif stat.S_ISDIR(info.st_mode):
            directories += 1
            records.append(f"D\0{relative}")
        elif stat.S_ISREG(info.st_mode):
            files += 1
            total_bytes += info.st_size
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            records.append(f"F\0{relative}\0{info.st_size}\0{digest.hexdigest()}")
        else:
            records.append(f"O\0{relative}\0{info.st_mode}")
    combined = hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()
    return Manifest(files, directories, symlinks, total_bytes, combined)


@dataclass(slots=True)
class MigrationEntry:
    release_id: str
    release_name: str
    release_status: str
    storage_path: str | None
    source: str
    destination: str
    source_type: str
    destination_type: str
    file_count: int | None
    backup_aliases: list[dict[str, str]] = field(default_factory=list)
    state: str = "unknown"
    issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _path_type(path: Path) -> str:
    if path.is_symlink():
        return "symlink" if path.exists() else "broken_symlink"
    if path.is_dir():
        return "directory"
    if path.is_file():
        return "file"
    return "missing"


def _backup_aliases(root: Path) -> dict[str, list[dict[str, str]]]:
    aliases: dict[str, list[dict[str, str]]] = {}
    if not root.is_dir():
        return aliases
    for path in root.iterdir():
        if ".backup-" not in path.name or not path.is_symlink():
            continue
        target_text = os.readlink(path)
        target = (path.parent / target_text).resolve() if not Path(target_text).is_absolute() else Path(target_text).resolve()
        aliases.setdefault(target.name, []).append(
            {"path": str(path), "target": str(target), "type": "symlink_alias"}
        )
    return aliases


def build_migration_plan(settings: Settings, engine: Engine) -> list[MigrationEntry]:
    root = settings.releases_root
    aliases = _backup_aliases(root)
    with Session(engine) as session:
        releases = list(session.scalars(select(VideoRelease).order_by(func.lower(VideoRelease.name))))
        occupied = [item.storage_path for item in releases if item.storage_path]
        proposed: dict[str, str] = {}
        for release in releases:
            if release.storage_path:
                proposed[release.id] = validate_storage_component(release.storage_path)
            else:
                component = choose_storage_component(release.name, release.id, occupied)
                proposed[release.id] = component
                occupied.append(component)

        result: list[MigrationEntry] = []
        for release in releases:
            current_component = storage_component_for_release(release.id, release.storage_path)
            source = root / current_component
            destination = root / proposed[release.id]
            source_type = _path_type(source)
            destination_type = _path_type(destination)
            entry = MigrationEntry(
                release_id=release.id,
                release_name=release.name,
                release_status=release.status,
                storage_path=release.storage_path,
                source=str(source),
                destination=str(destination),
                source_type=source_type,
                destination_type=destination_type,
                file_count=None,
                backup_aliases=aliases.get(release.id, []),
            )
            if release.storage_path:
                entry.state = "already_migrated" if source_type == "directory" else "configured_path_missing"
                if source_type != "directory":
                    entry.issues.append("database storage_path does not resolve to a real directory")
            elif source_type == "directory" and destination_type == "missing":
                manifest = directory_manifest(source)
                entry.file_count = manifest.files
                entry.state = "ready"
                if manifest.files == 0:
                    entry.issues.append("source directory is empty; migration is allowed but requires review")
            elif source_type == "missing" and destination_type == "directory":
                entry.file_count = directory_manifest(destination).files
                entry.state = "destination_only"
                entry.issues.append("possible interrupted migration; journal proof is required")
            elif source_type == "missing":
                entry.state = "missing_source"
                entry.issues.append("no current release directory was found; no directory will be created")
            else:
                entry.state = "conflict"
                if source_type != "directory":
                    entry.issues.append(f"legacy source is {source_type}, not a real directory")
                if destination_type != "missing":
                    entry.issues.append(f"destination already exists as {destination_type}")
            result.append(entry)
    return result


def _append_journal(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": datetime.now(timezone.utc).isoformat(), **payload}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _journal_moved_records(path: Path) -> dict[str, dict[str, Any]]:
    moved: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return moved
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        release_id = record.get("release_id")
        if record.get("phase") == "moved" and release_id:
            moved[release_id] = record
        if record.get("phase") in {"committed", "rolled_back"} and release_id:
            moved.pop(release_id, None)
    return moved


def execute_migration(
    settings: Settings,
    engine: Engine,
    *,
    confirmation: str,
    journal_path: Path,
    release_ids: set[str] | None = None,
) -> list[MigrationEntry]:
    if confirmation != EXECUTION_CONFIRMATION:
        raise ReleaseStorageError(
            f"execution requires --confirm {EXECUTION_CONFIRMATION}"
        )
    plan = build_migration_plan(settings, engine)
    selected = [entry for entry in plan if release_ids is None or entry.release_id in release_ids]
    if release_ids and release_ids != {entry.release_id for entry in selected}:
        raise ReleaseStorageError("one or more requested release IDs do not exist")
    interrupted = _journal_moved_records(journal_path)
    blockers = [entry for entry in selected if entry.state not in {"ready", "already_migrated", "missing_source", "destination_only"}]
    unproven = [entry for entry in selected if entry.state == "destination_only" and entry.release_id not in interrupted]
    if blockers or unproven:
        raise ReleaseStorageError("migration plan contains conflicts or an unproven interrupted move")

    for entry in selected:
        if entry.state in {"already_migrated", "missing_source"}:
            continue
        source = Path(entry.source)
        destination = Path(entry.destination)
        if entry.state == "destination_only":
            prior = interrupted[entry.release_id]
            manifest = directory_manifest(destination)
            if manifest.digest != prior.get("manifest", {}).get("digest"):
                raise ReleaseStorageError(f"interrupted move manifest differs for {entry.release_id}")
        else:
            before = directory_manifest(source)
            _append_journal(journal_path, {
                "phase": "planned", "release_id": entry.release_id,
                "source": str(source), "destination": str(destination),
                "manifest": asdict(before),
            })
            try:
                source.rename(destination)
            except OSError as exc:
                _append_journal(journal_path, {"phase": "failed", "release_id": entry.release_id, "error": str(exc)})
                raise ReleaseStorageError(f"could not move release {entry.release_id}: {exc}") from exc
            after = directory_manifest(destination)
            if after != before:
                destination.rename(source)
                _append_journal(journal_path, {"phase": "rolled_back", "release_id": entry.release_id, "reason": "manifest mismatch"})
                raise ReleaseStorageError(f"manifest changed while moving release {entry.release_id}")
            _append_journal(journal_path, {
                "phase": "moved", "release_id": entry.release_id,
                "source": str(source), "destination": str(destination),
                "manifest": asdict(after),
            })

        try:
            with Session(engine) as session:
                release = session.get(VideoRelease, entry.release_id)
                if release is None or release.storage_path is not None:
                    raise ReleaseStorageError("release database state changed during migration")
                duplicate = session.scalar(
                    select(VideoRelease).where(
                        func.lower(VideoRelease.storage_path) == destination.name.casefold(),
                        VideoRelease.id != release.id,
                    )
                )
                if duplicate is not None:
                    raise ReleaseStorageError("release storage path collided during migration")
                release.storage_path = validate_storage_component(destination.name)
                session.commit()
        except Exception as exc:
            with Session(engine) as verification_session:
                current_storage = verification_session.scalar(
                    select(VideoRelease.storage_path).where(VideoRelease.id == entry.release_id)
                )
            if current_storage == destination.name:
                _append_journal(journal_path, {
                    "phase": "committed", "release_id": entry.release_id,
                    "storage_path": destination.name, "recovered_after_error": str(exc),
                })
                continue
            if current_storage is None and not source.exists() and destination.is_dir() and not destination.is_symlink():
                destination.rename(source)
                _append_journal(journal_path, {"phase": "rolled_back", "release_id": entry.release_id, "reason": f"database update failed: {exc}"})
            raise
        _append_journal(journal_path, {"phase": "committed", "release_id": entry.release_id, "storage_path": destination.name})
    return build_migration_plan(settings, engine)
