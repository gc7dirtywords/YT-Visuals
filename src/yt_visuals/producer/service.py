from __future__ import annotations

import csv
import hashlib
import html
import ipaddress
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, selectinload

from ..acquisition import AcquisitionService, YT_VISUALS_USER_AGENT
from ..config import Settings
from ..library import LibraryScanner
from ..library.inspection import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    Candidate,
    MediaInspectionError,
    inspect_media_file,
)
from ..models import (
    MediaAsset,
    MediaSource,
    ProducerBeat,
    ProducerBeatHiddenAsset,
    ProducerWorkspace,
)
from ..providers.base import MediaProvider as ProviderClient
from ..providers.base import MediaSearchResult
from ..providers.errors import MediaDownloadError
from ..providers.registry import create_provider
from ..services import MediaCatalogService, SearchMediaRequest
from ..services.schemas import AssetDetailResult, SearchCandidateResult
from .contracts import VisualPlan, validate_visual_plan_file
from .storyboard import render_producer_storyboard


PEXELS_PAGE = re.compile(r"^/(photo|video)/(?:[^/]*-)?([0-9]+)/?$")
SAFE_NAME = re.compile(r"[^a-z0-9]+")
WIKIMEDIA_USER_AGENT = YT_VISUALS_USER_AGENT


class ProducerWorkflowError(RuntimeError):
    pass


ProviderFactory = Callable[[str, Settings], ProviderClient]
AcquisitionFactory = Callable[[Settings, Engine], AcquisitionService]


@dataclass(frozen=True, slots=True)
class WikimediaFileMetadata:
    direct_media_url: str
    source_page_url: str
    creator_attribution: str | None
    license_name: str | None
    license_url: str | None


WikimediaResolver = Callable[[str], WikimediaFileMetadata]


class ProducerWorkflowService:
    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        *,
        provider_factory: ProviderFactory = create_provider,
        acquisition_factory: AcquisitionFactory = AcquisitionService,
        wikimedia_resolver: WikimediaResolver | None = None,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.catalog = MediaCatalogService(engine)
        self.provider_factory = provider_factory
        self.acquisition_factory = acquisition_factory
        self.wikimedia_resolver = wikimedia_resolver or resolve_wikimedia_file_page

    @staticmethod
    def validate_plan_file(path: Path) -> VisualPlan:
        return validate_visual_plan_file(path)

    def import_plan_file(self, path: Path) -> dict[str, Any]:
        return self.import_plan(validate_visual_plan_file(path))

    def import_plan(self, plan: VisualPlan) -> dict[str, Any]:
        digest = plan.document_sha256()
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ProducerWorkspace).where(
                    func.lower(ProducerWorkspace.story_external_id)
                    == plan.story.story_id.casefold()
                )
            )
            if existing is not None:
                if existing.plan_document_sha256 != digest:
                    raise ProducerWorkflowError(
                        "a different Visual Plan already exists for this story ID"
                    )
                return self._import_result(existing, len(plan.beats), idempotent=True)

            workspace = ProducerWorkspace(
                id=str(uuid.uuid4()),
                story_external_id=plan.story.story_id,
                title=plan.story.title,
                plan_document_sha256=digest,
                plan_json=plan.model_dump(mode="json"),
            )
            session.add(workspace)
            for beat in sorted(plan.beats, key=lambda item: item.sequence):
                session.add(
                    ProducerBeat(
                        id=str(uuid.uuid4()),
                        workspace=workspace,
                        external_beat_id=beat.beat_id,
                        sequence=beat.sequence,
                        specification_json=beat.model_dump(mode="json"),
                    )
                )
            session.commit()
            return self._import_result(workspace, len(plan.beats), idempotent=False)

    @staticmethod
    def _import_result(
        workspace: ProducerWorkspace, beats: int, *, idempotent: bool
    ) -> dict[str, Any]:
        return {
            "workspace_id": workspace.id,
            "story_id": workspace.story_external_id,
            "title": workspace.title,
            "beats": beats,
            "idempotent": idempotent,
        }

    def list_workspaces(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ProducerWorkspace)
                    .options(selectinload(ProducerWorkspace.beats))
                    .order_by(ProducerWorkspace.updated_at.desc())
                )
            )
            return [
                {
                    "workspace_id": row.id,
                    "story_id": row.story_external_id,
                    "title": row.title,
                    "selected": sum(1 for beat in row.beats if beat.selected_asset_id),
                    "total": len(row.beats),
                }
                for row in rows
            ]

    def get_workspace(
        self, workspace_id: str, *, include_candidates: bool = True
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            workspace = session.scalar(
                select(ProducerWorkspace)
                .where(ProducerWorkspace.id == workspace_id)
                .options(
                    selectinload(ProducerWorkspace.beats).selectinload(
                        ProducerBeat.hidden_assets
                    )
                )
            )
            if workspace is None:
                raise ProducerWorkflowError("producer workspace was not found")
            rows = [
                {
                    "id": beat.id,
                    "beat_id": beat.external_beat_id,
                    "sequence": beat.sequence,
                    "specification": dict(beat.specification_json),
                    "selected_asset_id": beat.selected_asset_id,
                    "hidden_asset_ids": [item.asset_id for item in beat.hidden_assets],
                }
                for beat in workspace.beats
            ]
            result = {
                "workspace_id": workspace.id,
                "story_id": workspace.story_external_id,
                "title": workspace.title,
                "status": workspace.status,
                "edit_folder": str(self.edit_folder(workspace.story_external_id)),
                "storyboard": self._storyboard_view(workspace.story_external_id),
                "selected": sum(1 for row in rows if row["selected_asset_id"]),
                "total": len(rows),
                "beats": rows,
            }

        for beat in result["beats"]:
            selected_id = beat.pop("selected_asset_id")
            beat["selected"] = (
                self._asset_view(self.catalog.get_asset_detail(selected_id))
                if selected_id is not None
                else None
            )
            beat["candidates"] = (
                self.list_candidates(workspace_id, beat["id"], limit=3)
                if include_candidates
                else []
            )
        return result

    def list_candidates(
        self, workspace_id: str, beat_id: str, *, limit: int = 3
    ) -> list[dict[str, Any]]:
        beat, hidden = self._load_beat(workspace_id, beat_id)
        specification = beat.specification_json
        preference = specification["media_preference"]
        media_type = None if preference == "either" else preference
        merged: list[SearchCandidateResult] = []
        seen: set[int] = set()
        for query in specification["search_queries"]:
            response = self.catalog.search_media(
                SearchMediaRequest(query=query, media_type=media_type, limit=20)
            )
            for candidate in response.candidates:
                if candidate.asset_id in hidden or candidate.asset_id in seen:
                    continue
                seen.add(candidate.asset_id)
                merged.append(candidate)
                if len(merged) >= limit:
                    break
            if len(merged) >= limit:
                break
        return [
            self._candidate_view(item, self.catalog.get_asset_detail(item.asset_id))
            for item in merged
        ]

    def select_asset(
        self,
        workspace_id: str,
        beat_id: str,
        asset_id: int,
        *,
        rebuild_edit: bool = True,
    ) -> None:
        detail = self.catalog.get_asset_detail(asset_id)
        if not detail.available or not detail.sha256:
            raise ProducerWorkflowError("the selected asset is not locally available")
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            preference = beat.specification_json["media_preference"]
            if preference != "either" and detail.media_type != preference:
                raise ProducerWorkflowError(
                    f"this beat requires {preference} media, not {detail.media_type}"
                )
            beat.selected_asset_id = detail.asset_id
            beat.selected_asset_sha256 = detail.sha256
            beat.selected_at = datetime.now(timezone.utc)
            hidden = session.scalar(
                select(ProducerBeatHiddenAsset).where(
                    ProducerBeatHiddenAsset.beat_id == beat.id,
                    ProducerBeatHiddenAsset.asset_id == detail.asset_id,
                )
            )
            if hidden is not None:
                session.delete(hidden)
            session.commit()
        if rebuild_edit:
            self.build_edit_folder(workspace_id)

    def clear_selection(
        self, workspace_id: str, beat_id: str, *, rebuild_edit: bool = True
    ) -> None:
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            beat.selected_asset_id = None
            beat.selected_asset_sha256 = None
            beat.selected_at = None
            session.commit()
        if rebuild_edit:
            self.build_edit_folder(workspace_id)

    def hide_asset(
        self,
        workspace_id: str,
        beat_id: str,
        asset_id: int,
        *,
        rebuild_edit: bool = True,
    ) -> None:
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            asset = session.get(MediaAsset, asset_id)
            if asset is None:
                raise ProducerWorkflowError("asset was not found")
            hidden = session.scalar(
                select(ProducerBeatHiddenAsset).where(
                    ProducerBeatHiddenAsset.beat_id == beat.id,
                    ProducerBeatHiddenAsset.asset_id == asset_id,
                )
            )
            if hidden is None:
                session.add(ProducerBeatHiddenAsset(beat=beat, asset=asset))
            if beat.selected_asset_id == asset_id:
                beat.selected_asset_id = None
                beat.selected_asset_sha256 = None
                beat.selected_at = None
            session.commit()
        if rebuild_edit:
            self.build_edit_folder(workspace_id)

    def restore_asset(self, workspace_id: str, beat_id: str, asset_id: int) -> None:
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            hidden = session.scalar(
                select(ProducerBeatHiddenAsset).where(
                    ProducerBeatHiddenAsset.beat_id == beat.id,
                    ProducerBeatHiddenAsset.asset_id == asset_id,
                )
            )
            if hidden is not None:
                session.delete(hidden)
                session.commit()

    def import_pexels_page(
        self, workspace_id: str, beat_id: str, page_url: str
    ) -> dict[str, Any]:
        media_type, asset_id = parse_pexels_page_url(page_url)
        self._ensure_preference(workspace_id, beat_id, media_type)
        acquisition = self.acquisition_factory(self.settings, self.engine)
        provider: ProviderClient | None = None
        try:
            existing = acquisition.lookup_existing("pexels", media_type, asset_id)
            if existing is not None:
                outcome = existing
            else:
                provider = self.provider_factory("pexels", self.settings)
                result = (
                    provider.get_photo(asset_id)
                    if media_type == "image"
                    else provider.get_video(asset_id)
                )
                outcome = acquisition.acquire(result)
        finally:
            if provider is not None:
                provider.close()
            acquisition.close()
        self.select_asset(workspace_id, beat_id, outcome.asset_id)
        return {
            **outcome.to_dict(),
            "source_kind": "pexels_page",
            "media_type": media_type,
        }

    def import_upload(
        self,
        workspace_id: str,
        beat_id: str,
        temporary_path: Path,
        original_filename: str,
    ) -> dict[str, Any]:
        extension = Path(original_filename).suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            media_type = "image"
            maximum = self.settings.max_image_download_bytes
        elif extension in VIDEO_EXTENSIONS:
            media_type = "video"
            maximum = self.settings.max_video_download_bytes
        else:
            raise ProducerWorkflowError("unsupported upload file type")
        self._ensure_preference(workspace_id, beat_id, media_type)
        stat = temporary_path.stat()
        if stat.st_size > maximum:
            raise ProducerWorkflowError(f"upload exceeds the {maximum}-byte safety limit")
        candidate = Candidate(
            absolute_path=temporary_path,
            relative_path=f"Temp/{temporary_path.name}",
            media_type=media_type,
            extension=extension,
            file_size_bytes=stat.st_size,
            file_modified_ns=stat.st_mtime_ns,
            file_modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )
        try:
            inspected = inspect_media_file(candidate)
        except MediaInspectionError as exc:
            raise ProducerWorkflowError(f"uploaded media is invalid: {exc}") from exc

        with Session(self.engine) as session:
            existing = session.scalar(
                select(MediaAsset).where(MediaAsset.sha256 == inspected.sha256)
            )
            existing_id = existing.id if existing is not None else None
        detail = self.catalog.get_asset_detail(existing_id) if existing_id else None
        if detail is None or not detail.available:
            destination_dir = self.settings.root / "Library" / (
                "Images" if media_type == "image" else "Videos"
            )
            destination_dir.mkdir(parents=True, exist_ok=True)
            label = _safe_label(Path(original_filename).stem, fallback="upload")
            destination = destination_dir / f"upload-{label}-{inspected.sha256[:10]}{extension}"
            if not destination.exists():
                shutil.copy2(temporary_path, destination)
            LibraryScanner(self.settings, self.engine).scan()
            with Session(self.engine) as session:
                asset = session.scalar(
                    select(MediaAsset).where(MediaAsset.sha256 == inspected.sha256)
                )
                if asset is None:
                    raise ProducerWorkflowError("uploaded media could not be cataloged")
                existing_id = asset.id

        with Session(self.engine) as session:
            asset = session.get(MediaAsset, existing_id)
            if asset is None:
                raise ProducerWorkflowError("uploaded media could not be cataloged")
            metadata = dict(asset.technical_metadata or {})
            uploads = list(metadata.get("producer_uploads", []))
            if original_filename not in uploads:
                uploads.append(original_filename)
            metadata["producer_uploads"] = uploads
            asset.technical_metadata = metadata
            if not any(
                source.provider_id is None
                and source.original_filename == original_filename
                and source.source_url is None
                for source in asset.sources
            ):
                session.add(
                    MediaSource(
                        asset=asset,
                        original_filename=original_filename,
                        acquired_at=datetime.now(timezone.utc),
                    )
                )
            session.commit()
        self.select_asset(workspace_id, beat_id, existing_id)
        return {
            "asset_id": existing_id,
            "sha256": inspected.sha256,
            "media_type": media_type,
            "deduplicated": detail is not None,
            "source_kind": "local_upload",
        }

    def import_external_media(
        self,
        workspace_id: str,
        beat_id: str,
        direct_media_url: str,
        *,
        source_page_url: str | None = None,
        creator_attribution: str | None = None,
        license_name: str | None = None,
        license_url: str | None = None,
    ) -> dict[str, Any]:
        resolved = (
            self.wikimedia_resolver(direct_media_url)
            if _is_wikimedia_file_page(direct_media_url)
            else None
        )
        direct_url = _validated_https_url(
            resolved.direct_media_url if resolved else direct_media_url,
            field="Direct media URL",
            required=True,
        )
        source_url = _validated_https_url(
            source_page_url or (resolved.source_page_url if resolved else None),
            field="Source page URL",
        )
        normalized_license_url = _validated_https_url(
            license_url or (resolved.license_url if resolved else None),
            field="License URL",
        )
        parsed = urlsplit(direct_url)
        extension = Path(parsed.path).suffix.casefold()
        if extension in IMAGE_EXTENSIONS:
            media_type = "image"
        elif extension in VIDEO_EXTENSIONS:
            media_type = "video"
        elif extension in {".gif", ".svg"}:
            raise ProducerWorkflowError(
                "Unsupported media URL type. GIF and SVG are not supported."
            )
        else:
            raise ProducerWorkflowError(
                "This URL did not resolve to a supported media file. "
                "Provide the direct image/video URL."
            )
        self._ensure_preference(workspace_id, beat_id, media_type)

        creator = (creator_attribution or (resolved.creator_attribution if resolved else "") or "").strip() or None
        supplied_license_name = (license_name or (resolved.license_name if resolved else "") or "").strip()
        result = MediaSearchResult(
            provider="manual_external",
            provider_asset_id=hashlib.sha256(direct_url.encode("utf-8")).hexdigest(),
            media_type=media_type,
            title=Path(parsed.path).stem[:255] or "Manual external media",
            description="Manually supplied direct media URL",
            creator_name=creator,
            creator_url=None,
            source_url=source_url or direct_url,
            download_url=direct_url,
            preview_url=None,
            width=None,
            height=None,
            duration_ms=None,
            mime_type=None,
            license_name=supplied_license_name,
            license_url=normalized_license_url or (resolved.license_url if resolved else "") or "",
            attribution_required=False,
            attribution_text=creator,
            raw_metadata={"source_kind": "manual_external"},
            commercial_use_allowed=None,
            modifications_allowed=None,
            license_notes=None,
        )
        acquisition = self.acquisition_factory(self.settings, self.engine)
        acquisition.allowed_download_hosts = frozenset({parsed.hostname or ""})
        try:
            outcome = acquisition.acquire(result)
        except MediaDownloadError as exc:
            if getattr(exc, "category", None) in {
                "mime_mismatch",
                "invalid_image",
                "invalid_video",
            }:
                raise ProducerWorkflowError(
                    "This URL did not resolve to a supported media file. "
                    "Provide the direct image/video URL."
                ) from exc
            raise ProducerWorkflowError(str(exc)) from exc
        finally:
            acquisition.close()
        self.select_asset(workspace_id, beat_id, outcome.asset_id)
        return {
            **outcome.to_dict(),
            "source_kind": "manual_external",
            "media_type": media_type,
            "source_page_url": source_url,
            "direct_media_url": direct_url,
        }

    def build_edit_folder(
        self,
        workspace_id: str,
        *,
        linker: Callable[[str | bytes | os.PathLike[str] | os.PathLike[bytes], str | bytes | os.PathLike[str] | os.PathLike[bytes]], None] = os.link,
        copier: Callable[[str | os.PathLike[str], str | os.PathLike[str]], Any] = shutil.copy2,
    ) -> dict[str, Any]:
        workspace = self.get_workspace(workspace_id, include_candidates=False)
        edit_root = self.edit_folder(workspace["story_id"])
        staging = self.settings.root / "Temp" / f"edit-build-{uuid.uuid4()}"
        staging_visuals = staging / "Visuals"
        staging_visuals.mkdir(parents=True)
        rows: list[dict[str, Any]] = []
        max_sequence = max((beat["sequence"] for beat in workspace["beats"]), default=1)
        prefix_width = max(3, len(str(max_sequence)))
        try:
            for beat in workspace["beats"]:
                selected = beat["selected"]
                if selected is None:
                    continue
                source_path = self.settings.root / selected["current_location"]
                if not source_path.is_file():
                    raise ProducerWorkflowError(
                        f"selected asset for {beat['beat_id']} is missing"
                    )
                label = _safe_label(
                    beat["specification"]["desired_visual"],
                    fallback=beat["beat_id"],
                )
                filename = (
                    f"{beat['sequence']:0{prefix_width}d}-{label[:64]}"
                    f"{source_path.suffix.lower()}"
                )
                destination = staging_visuals / filename
                mode = "hardlink"
                try:
                    linker(source_path, destination)
                except OSError:
                    copier(source_path, destination)
                    mode = "copy"
                source = selected["source"]
                license_record = selected["license"]
                rows.append(
                    {
                        "sequence": beat["sequence"],
                        "beat_id": beat["beat_id"],
                        "filename": filename,
                        "asset_id": selected["asset_id"],
                        "media_type": selected["media_type"],
                        "source_provider": source["provider"] or source["origin"],
                        "source_url": source["source_url"] or "",
                        "creator": source["creator_name"] or "",
                        "license_status": license_record["status"],
                        "license_name": license_record["name"] or "",
                        "transfer_mode": mode,
                    }
                )
            manifest = staging / "manifest.csv"
            with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
                fieldnames = list(rows[0].keys()) if rows else [
                    "sequence", "beat_id", "filename", "asset_id", "media_type",
                    "source_provider", "source_url", "creator", "license_status",
                    "license_name", "transfer_mode",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            edit_root.mkdir(parents=True, exist_ok=True)
            visuals = edit_root / "Visuals"
            _assert_within(visuals, edit_root)
            if visuals.exists():
                shutil.rmtree(visuals)
            shutil.move(str(staging_visuals), str(visuals))
            shutil.copy2(manifest, edit_root / "manifest.csv")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return {"edit_folder": str(edit_root), "entries": rows}

    def generate_storyboard(self, workspace_id: str) -> dict[str, Any]:
        workspace = self.get_workspace(workspace_id, include_candidates=False)
        destination = self.edit_folder(workspace["story_id"]) / "storyboard.pdf"
        pages = render_producer_storyboard(workspace, destination, root=self.settings.root)
        return {"storyboard_path": str(destination), "pages": pages}

    def storyboard_path(self, workspace_id: str) -> Path:
        workspace = self.get_workspace(workspace_id, include_candidates=False)
        path = self.edit_folder(workspace["story_id"]) / "storyboard.pdf"
        _assert_within(path, self.settings.root / "Projects")
        if not path.is_file():
            raise ProducerWorkflowError("generate the storyboard before opening it")
        return path

    def open_storyboard(
        self, workspace_id: str, *, opener: Callable[[str], Any] | None = None
    ) -> str:
        path = self.storyboard_path(workspace_id)
        self._open_trusted_path(path, opener=opener, kind="storyboard")
        return str(path)

    def open_storyboard_folder(
        self, workspace_id: str, *, opener: Callable[[str], Any] | None = None
    ) -> str:
        path = self.storyboard_path(workspace_id).parent
        self._open_trusted_path(path, opener=opener, kind="storyboard folder")
        return str(path)

    def edit_folder(self, story_id: str) -> Path:
        return self.settings.root / "Projects" / story_id / "Edit"

    def open_edit_folder(
        self, workspace_id: str, *, opener: Callable[[str], Any] | None = None
    ) -> str:
        workspace = self.get_workspace(workspace_id, include_candidates=False)
        path = self.edit_folder(workspace["story_id"])
        path.mkdir(parents=True, exist_ok=True)
        if opener is not None:
            opener(str(path))
        elif hasattr(os, "startfile"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            raise ProducerWorkflowError("opening folders is supported only on local Windows")
        return str(path)

    @staticmethod
    def _open_trusted_path(
        path: Path,
        *,
        opener: Callable[[str], Any] | None,
        kind: str,
    ) -> None:
        try:
            if opener is not None:
                opener(str(path))
            elif hasattr(os, "startfile"):
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                raise OSError("local OS opener is unavailable")
        except OSError as exc:
            raise ProducerWorkflowError(f"the {kind} could not be opened") from exc

    def asset_path(self, asset_id: int) -> Path:
        detail = self.catalog.get_asset_detail(asset_id)
        if not detail.current_location:
            raise ProducerWorkflowError("asset is not locally available")
        path = self.settings.root / detail.current_location
        _assert_within(path, self.settings.root / "Library")
        if not path.is_file():
            raise ProducerWorkflowError("asset file is missing")
        return path

    def _ensure_preference(
        self, workspace_id: str, beat_id: str, media_type: str
    ) -> None:
        beat, _hidden = self._load_beat(workspace_id, beat_id)
        preference = beat.specification_json["media_preference"]
        if preference != "either" and preference != media_type:
            raise ProducerWorkflowError(
                f"this beat requires {preference} media, not {media_type}"
            )

    def beat_anchor(self, workspace_id: str, beat_id: str) -> str:
        beat, _hidden = self._load_beat(workspace_id, beat_id)
        return beat.external_beat_id

    def _load_beat(
        self, workspace_id: str, beat_id: str
    ) -> tuple[ProducerBeat, set[int]]:
        with Session(self.engine) as session:
            beat = session.scalar(
                select(ProducerBeat)
                .where(
                    ProducerBeat.workspace_id == workspace_id,
                    ProducerBeat.id == beat_id,
                )
                .options(selectinload(ProducerBeat.hidden_assets))
            )
            if beat is None:
                raise ProducerWorkflowError("producer beat was not found")
            session.expunge(beat)
            return beat, {item.asset_id for item in beat.hidden_assets}

    @staticmethod
    def _session_beat(
        session: Session, workspace_id: str, beat_id: str
    ) -> ProducerBeat:
        beat = session.scalar(
            select(ProducerBeat).where(
                ProducerBeat.workspace_id == workspace_id,
                ProducerBeat.id == beat_id,
            )
        )
        if beat is None:
            raise ProducerWorkflowError("producer beat was not found")
        return beat

    @staticmethod
    def _candidate_view(
        candidate: SearchCandidateResult, detail: AssetDetailResult
    ) -> dict[str, Any]:
        result = ProducerWorkflowService._asset_view(detail)
        result.update(
            {
                "rank": candidate.rank,
                "score": candidate.score,
                "score_reasons": list(candidate.score_reasons),
                "recent_usage_count": candidate.recent_usage_count,
            }
        )
        return result

    @staticmethod
    def _asset_view(detail: AssetDetailResult) -> dict[str, Any]:
        license_record = detail.license
        source = _preferred_source(detail, license_record)
        origin = "local_upload" if any(
            item.provenance_type == "local_import" for item in detail.locations
        ) else "provider_download"
        return {
            "asset_id": detail.asset_id,
            "relative_path": detail.relative_path,
            "current_location": detail.current_location,
            "media_type": detail.media_type,
            "mime_type": detail.mime_type,
            "width": detail.width,
            "height": detail.height,
            "duration_ms": detail.duration_ms,
            "available": detail.available,
            "usage_count": detail.usage_count,
            "last_used_at": detail.last_used_at.isoformat() if detail.last_used_at else None,
            "source": {
                "origin": origin,
                "provider": source.provider if source else None,
                "source_url": source.source_url if source else None,
                "creator_name": source.creator_name if source else None,
                "original_filename": source.original_filename if source else None,
            },
            "license": {
                "status": "known" if license_record and license_record.license_name else "unknown",
                "name": license_record.license_name if license_record else None,
                "url": license_record.license_url if license_record else None,
                "attribution_required": (
                    license_record.attribution_required if license_record else False
                ),
                "attribution_text": license_record.attribution_text if license_record else None,
            },
        }

    def _storyboard_view(self, story_id: str) -> dict[str, Any]:
        path = self.edit_folder(story_id) / "storyboard.pdf"
        return {
            "exists": path.is_file(),
            "path": str(path),
        }


def parse_pexels_page_url(value: str) -> tuple[str, str]:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in {
        "pexels.com",
        "www.pexels.com",
    }:
        raise ProducerWorkflowError("only HTTPS Pexels photo or video page URLs are supported")
    match = PEXELS_PAGE.fullmatch(parsed.path)
    if match is None:
        raise ProducerWorkflowError("the URL is not a recognized Pexels photo or video page")
    kind, asset_id = match.groups()
    return ("image" if kind == "photo" else "video"), asset_id


def _validated_https_url(
    value: str | None, *, field: str, required: bool = False
) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        if required:
            raise ProducerWorkflowError(f"{field} is required")
        return None
    parsed = urlsplit(normalized)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or not host or parsed.username or parsed.password:
        raise ProducerWorkflowError(f"{field} must be a valid HTTPS URL")
    if host == "localhost" or host.endswith(".localhost"):
        raise ProducerWorkflowError(f"{field} must use a public HTTPS host")
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ProducerWorkflowError(f"{field} must use a public HTTPS host")
    return normalized


def _preferred_source(detail: AssetDetailResult, license_record: Any):
    """Choose the most useful documented source without discarding other provenance."""
    if not detail.sources:
        return None
    license_known = bool(license_record and license_record.license_name)

    def priority(source: Any) -> tuple[int, int, int, int, str]:
        documented_page = int(bool(source.source_url))
        documented_creator = int(bool(source.creator_name))
        provider_backed = int(bool(source.provider))
        licensed_page = int(license_known and documented_page)
        acquired = source.acquired_at.isoformat() if source.acquired_at else ""
        return (licensed_page, documented_page, documented_creator, provider_backed, acquired)

    return max(detail.sources, key=priority)


def _is_wikimedia_file_page(value: str) -> bool:
    parsed = urlsplit(value.strip())
    if (parsed.hostname or "").casefold() != "commons.wikimedia.org":
        return False
    title = parse_qs(parsed.query).get("title", [""])[0]
    return parsed.path.casefold().startswith("/wiki/file:") or title.casefold().startswith("file:")


def resolve_wikimedia_file_page(
    value: str, *, http_client: httpx.Client | None = None
) -> WikimediaFileMetadata:
    page_url = _validated_https_url(value, field="Wikimedia Commons file page", required=True)
    parsed = urlsplit(page_url)
    if (parsed.hostname or "").casefold() != "commons.wikimedia.org":
        raise ProducerWorkflowError("only Wikimedia Commons file pages are supported")
    title = ""
    if parsed.path.casefold().startswith("/wiki/file:"):
        title = unquote(parsed.path[len("/wiki/") :])
    elif parsed.path.casefold() == "/w/index.php":
        title = parse_qs(parsed.query).get("title", [""])[0]
    if not title.casefold().startswith("file:"):
        raise ProducerWorkflowError("the Wikimedia Commons URL is not a file page")

    try:
        client = http_client or httpx.Client(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": WIKIMEDIA_USER_AGENT},
        )
        response = client.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "titles": title,
            },
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ProducerWorkflowError("Wikimedia Commons could not resolve that file page") from exc
    finally:
        if http_client is None and "client" in locals():
            client.close()

    try:
        page = payload["query"]["pages"][0]
        info = page["imageinfo"][0]
        direct_media_url = info["url"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProducerWorkflowError("Wikimedia Commons returned no original media file") from exc
    if not isinstance(direct_media_url, str):
        raise ProducerWorkflowError("Wikimedia Commons returned an invalid media URL")

    metadata = info.get("extmetadata") if isinstance(info, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    creator = _wikimedia_metadata_text(metadata, "Artist", "Author", "Credit")
    license_name = _wikimedia_metadata_text(metadata, "LicenseShortName", "License")
    license_url = _wikimedia_metadata_text(metadata, "LicenseUrl")
    source_page_url = info.get("descriptionurl") if isinstance(info, dict) else None
    if not isinstance(source_page_url, str):
        source_page_url = page_url
    return WikimediaFileMetadata(
        direct_media_url=direct_media_url,
        source_page_url=source_page_url,
        creator_attribution=creator,
        license_name=license_name,
        license_url=license_url,
    )


def _wikimedia_metadata_text(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        item = metadata.get(key)
        value = item.get("value") if isinstance(item, dict) else item
        if not isinstance(value, str):
            continue
        text = html.unescape(re.sub(r"<[^>]*>", " ", value))
        text = " ".join(text.split())
        if text:
            return text
    return None


def _safe_label(value: str, *, fallback: str) -> str:
    label = SAFE_NAME.sub("-", value.casefold()).strip("-.")
    return label or SAFE_NAME.sub("-", fallback.casefold()).strip("-.") or "asset"


def _assert_within(path: Path, parent: Path) -> None:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
    except ValueError as exc:
        raise ProducerWorkflowError("generated path escaped its intended root") from exc
