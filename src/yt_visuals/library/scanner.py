from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, selectinload

from ..config import Settings
from ..models import MediaAsset, MediaLocation
from .inspection import (
    Candidate,
    InspectedMedia,
    MediaInspectionError,
    discover_library_files,
    inspect_media_file,
)


@dataclass(frozen=True, slots=True)
class ScanError:
    relative_path: str
    category: str
    message: str


@dataclass(slots=True)
class ScanSummary:
    dry_run: bool
    files_scanned: int = 0
    new_assets: int = 0
    existing_assets: int = 0
    unchanged_files: int = 0
    updated_files: int = 0
    duplicate_hashes: int = 0
    moved_paths: int = 0
    restored_paths: int = 0
    missing_paths: int = 0
    missing_assets: int = 0
    skipped_symlinks: int = 0
    errors: list[ScanError] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["error_count"] = self.error_count
        return result


Inspector = Callable[[Candidate], InspectedMedia]


class LibraryScanner:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        *,
        inspector: Inspector = inspect_media_file,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.inspector = inspector

    def scan(self, *, dry_run: bool = False, verbose: bool = False) -> ScanSummary:
        candidates, discovery_errors, skipped_symlinks = discover_library_files(self.settings.root)
        summary = ScanSummary(
            dry_run=dry_run,
            files_scanned=len(candidates),
            skipped_symlinks=skipped_symlinks,
            errors=[ScanError(item.relative_path, item.category, item.message) for item in discovery_errors],
        )
        candidate_paths = {item.relative_path.casefold() for item in candidates}
        now = datetime.now(timezone.utc)

        with Session(self.engine) as session:
            locations = list(
                session.scalars(select(MediaLocation).options(selectinload(MediaLocation.asset)))
            )
            locations_by_path = {item.relative_path.casefold(): item for item in locations}
            assets = list(session.scalars(select(MediaAsset).options(selectinload(MediaAsset.locations))))
            assets_by_path = {item.relative_path.casefold(): item for item in assets}
            assets_by_hash = {item.sha256: item for item in assets if item.sha256}
            planned_hashes: set[str] = set()
            present_asset_ids: set[int] = set()

            for candidate in candidates:
                key = candidate.relative_path.casefold()
                location = locations_by_path.get(key)
                if location is not None:
                    present_asset_ids.add(location.media_asset_id)
                if location is not None and self._is_unchanged(location, candidate):
                    summary.existing_assets += 1
                    summary.unchanged_files += 1
                    if location.status == "missing":
                        summary.restored_paths += 1
                        self._action(summary, verbose, f"restore {candidate.relative_path}")
                    if not dry_run:
                        location.status = "available"
                        location.last_seen_at = now
                        location.missing_since = None
                        location.asset.status = "active"
                        location.asset.last_verified_at = now
                    continue

                try:
                    inspected = self.inspector(candidate)
                except (MediaInspectionError, OSError, ValueError) as exc:
                    summary.errors.append(
                        ScanError(candidate.relative_path, type(exc).__name__, _concise(str(exc)))
                    )
                    self._action(summary, verbose, f"error {candidate.relative_path}: {_concise(str(exc))}")
                    continue

                target = assets_by_hash.get(inspected.sha256)
                if target is None and inspected.sha256 in planned_hashes:
                    summary.existing_assets += 1
                    summary.duplicate_hashes += 1
                    self._action(summary, verbose, f"duplicate {candidate.relative_path}")
                    continue

                if target is None and location is None:
                    legacy = assets_by_path.get(key)
                    if legacy is not None and (legacy.sha256 is None or legacy.sha256 == inspected.sha256):
                        target = legacy

                if target is None and location is not None:
                    siblings = [item for item in location.asset.locations if item is not location]
                    if siblings:
                        summary.errors.append(
                            ScanError(
                                candidate.relative_path,
                                "CatalogConflict",
                                "file bytes changed at one path of a multi-path asset; "
                                "the catalog was left unchanged",
                            )
                        )
                        self._action(summary, verbose, f"conflict {candidate.relative_path}")
                        continue
                    target = location.asset
                    if target.sha256:
                        assets_by_hash.pop(target.sha256, None)
                    assets_by_hash[inspected.sha256] = target

                if target is None:
                    summary.new_assets += 1
                    planned_hashes.add(inspected.sha256)
                    self._action(summary, verbose, f"add {candidate.relative_path}")
                    if dry_run:
                        continue
                    target = self._new_asset(inspected, now)
                    session.add(target)
                    session.flush()
                    assets_by_hash[inspected.sha256] = target
                    assets_by_path[key] = target
                    location = self._new_location(target, inspected, now)
                    session.add(location)
                    locations_by_path[key] = location
                    continue

                summary.existing_assets += 1
                present_asset_ids.add(target.id)
                is_new_path = location is None
                is_canonical_bootstrap = (
                    is_new_path and target.relative_path.casefold() == candidate.relative_path.casefold()
                )
                if is_new_path and not is_canonical_bootstrap:
                    if self._looks_moved(target, candidate_paths, candidate.relative_path):
                        summary.moved_paths += 1
                        self._action(summary, verbose, f"move {target.relative_path} -> {candidate.relative_path}")
                        if not dry_run:
                            target.relative_path = candidate.relative_path
                    else:
                        summary.duplicate_hashes += 1
                        self._action(summary, verbose, f"associate copy {candidate.relative_path}")
                elif location is not None and location.status == "missing":
                    summary.restored_paths += 1
                    self._action(summary, verbose, f"restore {candidate.relative_path}")
                elif location is not None:
                    summary.updated_files += 1
                    self._action(summary, verbose, f"update {candidate.relative_path}")

                if dry_run:
                    continue
                if location is None:
                    location = self._new_location(target, inspected, now)
                    session.add(location)
                    locations_by_path[key] = location
                elif location.asset is not target:
                    previous_asset = location.asset
                    location.asset = target
                    self._refresh_asset_status(previous_asset)
                self._update_location(location, inspected, now)
                self._update_asset(target, inspected, now)

            self._reconcile_missing(
                session,
                locations,
                assets,
                candidate_paths,
                now,
                summary,
                present_asset_ids,
                dry_run=dry_run,
                verbose=verbose,
            )
            if dry_run:
                session.rollback()
            else:
                session.flush()
                for asset in assets:
                    self._refresh_asset_status(asset)
                session.commit()
        return summary

    @staticmethod
    def _is_unchanged(location: MediaLocation, candidate: Candidate) -> bool:
        return (
            location.file_size_bytes == candidate.file_size_bytes
            and location.file_modified_ns == candidate.file_modified_ns
            and location.asset.sha256 is not None
        )

    @staticmethod
    def _new_asset(inspected: InspectedMedia, now: datetime) -> MediaAsset:
        candidate = inspected.candidate
        return MediaAsset(
            relative_path=candidate.relative_path,
            media_type=candidate.media_type,
            status="active",
            title=candidate.absolute_path.stem,
            mime_type=inspected.mime_type,
            file_size_bytes=candidate.file_size_bytes,
            sha256=inspected.sha256,
            width=inspected.width,
            height=inspected.height,
            duration_ms=inspected.duration_ms,
            file_modified_at=candidate.file_modified_at,
            last_verified_at=now,
            technical_metadata=_local_metadata(inspected),
        )

    @staticmethod
    def _new_location(asset: MediaAsset, inspected: InspectedMedia, now: datetime) -> MediaLocation:
        candidate = inspected.candidate
        return MediaLocation(
            asset=asset,
            relative_path=candidate.relative_path,
            status="available",
            provenance_type="local_import",
            file_size_bytes=candidate.file_size_bytes,
            file_modified_ns=candidate.file_modified_ns,
            file_modified_at=candidate.file_modified_at,
            first_seen_at=now,
            last_seen_at=now,
        )

    @staticmethod
    def _update_location(
        location: MediaLocation, inspected: InspectedMedia, now: datetime
    ) -> None:
        candidate = inspected.candidate
        location.status = "available"
        location.file_size_bytes = candidate.file_size_bytes
        location.file_modified_ns = candidate.file_modified_ns
        location.file_modified_at = candidate.file_modified_at
        location.last_seen_at = now
        location.missing_since = None

    @staticmethod
    def _update_asset(asset: MediaAsset, inspected: InspectedMedia, now: datetime) -> None:
        candidate = inspected.candidate
        metadata = dict(asset.technical_metadata or {})
        metadata.update(_local_metadata(inspected))
        asset.status = "active"
        asset.mime_type = inspected.mime_type
        asset.file_size_bytes = candidate.file_size_bytes
        asset.sha256 = inspected.sha256
        asset.width = inspected.width
        asset.height = inspected.height
        asset.duration_ms = inspected.duration_ms
        asset.file_modified_at = candidate.file_modified_at
        asset.last_verified_at = now
        asset.technical_metadata = metadata

    @staticmethod
    def _looks_moved(asset: MediaAsset, candidate_paths: set[str], new_path: str) -> bool:
        old_paths = [item.relative_path for item in asset.locations]
        if not old_paths and asset.relative_path.casefold() != new_path.casefold():
            old_paths.append(asset.relative_path)
        return bool(old_paths) and not any(path.casefold() in candidate_paths for path in old_paths)

    @staticmethod
    def _reconcile_missing(
        session: Session,
        locations: list[MediaLocation],
        assets: list[MediaAsset],
        candidate_paths: set[str],
        now: datetime,
        summary: ScanSummary,
        present_asset_ids: set[int],
        *,
        dry_run: bool,
        verbose: bool,
    ) -> None:
        for location in locations:
            if not _is_library_path(location.relative_path):
                continue
            if location.relative_path.casefold() in candidate_paths:
                continue
            if location.status == "available":
                summary.missing_paths += 1
                LibraryScanner._action(summary, verbose, f"missing {location.relative_path}")
                if not dry_run:
                    location.status = "missing"
                    location.missing_since = now

        located_asset_ids = {item.media_asset_id for item in locations}
        for asset in assets:
            if asset.id in located_asset_ids or not _is_library_path(asset.relative_path):
                continue
            if asset.relative_path.casefold() in candidate_paths:
                continue
            summary.missing_paths += 1
            LibraryScanner._action(summary, verbose, f"missing {asset.relative_path}")
            if not dry_run:
                session.add(
                    MediaLocation(
                        asset=asset,
                        relative_path=asset.relative_path,
                        status="missing",
                        provenance_type="provider_download" if asset.sources else "local_import",
                        file_size_bytes=asset.file_size_bytes,
                        file_modified_at=asset.file_modified_at,
                        first_seen_at=now,
                        last_seen_at=now,
                        missing_since=now,
                    )
                )
                asset.status = "missing"

        summary.missing_assets = sum(
            1
            for asset in assets
            if asset.id not in present_asset_ids
            and asset.status != "missing"
            and _is_library_path(asset.relative_path)
        )

    @staticmethod
    def _refresh_asset_status(asset: MediaAsset) -> None:
        available = [item for item in asset.locations if item.status == "available"]
        asset.status = "active" if available else "missing"
        if available and not any(
            item.relative_path.casefold() == asset.relative_path.casefold() for item in available
        ):
            asset.relative_path = min(available, key=lambda item: item.relative_path.casefold()).relative_path

    @staticmethod
    def _action(summary: ScanSummary, verbose: bool, message: str) -> None:
        if verbose:
            summary.actions.append(message)


def _local_metadata(inspected: InspectedMedia) -> dict[str, Any]:
    candidate = inspected.candidate
    return {
        "local_file": {
            "filename": candidate.absolute_path.name,
            "extension": candidate.extension,
            **inspected.technical_metadata,
        }
    }


def _is_library_path(relative_path: str) -> bool:
    normalized = relative_path.replace("\\", "/").casefold()
    return normalized.startswith("library/images/") or normalized.startswith("library/videos/")


def _concise(message: str) -> str:
    return " ".join(message.split())[:500]
