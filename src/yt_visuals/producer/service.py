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
from datetime import date, datetime, timezone
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
    AUDIO_EXTENSIONS,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    Candidate,
    MediaInspectionError,
    inspect_media_file,
)
from ..models import (
    MediaAsset,
    MediaSource,
    ProductionEvent,
    ProducerBeat,
    ProducerBeatHiddenAsset,
    ProducerWorkspace,
    ReleasePresentationRevision,
    VideoRelease,
)
from ..providers.base import MediaProvider as ProviderClient
from ..providers.base import MediaSearchResult
from ..providers.errors import MediaDownloadError
from ..providers.registry import create_provider
from ..services import MediaCatalogService, SearchMediaRequest
from ..services.errors import MediaServiceError
from ..services.schemas import AssetDetailResult, SearchCandidateResult
from .contracts import VisualPlan, validate_visual_plan_file
from .storyboard import render_producer_storyboard


PEXELS_PAGE = re.compile(r"^/(photo|video)/(?:[^/]*-)?([0-9]+)/?$")
SAFE_NAME = re.compile(r"[^a-z0-9]+")
WIKIMEDIA_USER_AGENT = YT_VISUALS_USER_AGENT
RELEASE_WORKSPACE_STATUS = {
    "planned": "planned",
    "in_production": "in_production",
    "scheduled": "completed",
    "released": "completed",
}
_PRESENTATION_UNSET = object()


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
            self._record_event(
                session,
                "workspace",
                workspace.id,
                "workspace.created",
                after={
                    "story_id": workspace.story_external_id,
                    "title": workspace.title,
                    "status": workspace.status,
                    "video_release_id": None,
                    "release_position": None,
                },
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
                    .options(selectinload(ProducerWorkspace.beats), selectinload(ProducerWorkspace.video_release))
                    .order_by(ProducerWorkspace.status, ProducerWorkspace.updated_at.desc())
                )
            )
            return [
                {
                    "workspace_id": row.id,
                    "story_id": row.story_external_id,
                    "title": row.title,
                    "selected": sum(1 for beat in row.beats if beat.selected_asset_id),
                    "total": len(row.beats),
                    "status": row.status,
                    "release": self._release_view(row.video_release),
                    "release_position": row.release_position,
                }
                for row in rows
            ]

    def get_workspace(
        self,
        workspace_id: str,
        *,
        include_candidates: bool = True,
        local_query: str = "",
        local_beat_id: str | None = None,
        sfx_query: str = "",
        sfx_beat_id: str | None = None,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            workspace = session.scalar(
                select(ProducerWorkspace)
                .where(ProducerWorkspace.id == workspace_id)
                .options(
                    selectinload(ProducerWorkspace.beats).selectinload(
                        ProducerBeat.hidden_assets
                    ), selectinload(ProducerWorkspace.video_release).selectinload(
                        VideoRelease.workspaces
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
                    "selected_sfx_asset_id": beat.selected_sfx_asset_id,
                    "hidden_asset_ids": [item.asset_id for item in beat.hidden_assets],
                }
                for beat in workspace.beats
            ]
            result = {
                "workspace_id": workspace.id,
                "story_id": workspace.story_external_id,
                "title": workspace.title,
                "status": workspace.status,
                "release": self._release_view(workspace.video_release),
                "release_position": workspace.release_position,
                "release_count": len(workspace.video_release.workspaces) if workspace.video_release else 0,
                "edit_folder": str(self.edit_folder(workspace.story_external_id)),
                "storyboard": self._storyboard_view(workspace.story_external_id),
                "selected": sum(1 for row in rows if row["selected_asset_id"]),
                "selected_sfx": sum(1 for row in rows if row["selected_sfx_asset_id"]),
                "total": len(rows),
                "beats": rows,
                "history": self._event_views(session, "workspace", workspace.id),
            }

        reuse_groups = self._reuse_groups(workspace_id, result["release"])
        sfx_reuse_groups = self._sfx_reuse_groups(workspace_id, result["release"])
        for beat in result["beats"]:
            selected_id = beat.pop("selected_asset_id")
            beat["selected"] = (
                self._asset_view(self.catalog.get_asset_detail(selected_id))
                if selected_id is not None
                else None
            )
            selected_sfx_id = beat.pop("selected_sfx_asset_id")
            beat["selected_sfx"] = (
                self._asset_view(self.catalog.get_asset_detail(selected_sfx_id))
                if selected_sfx_id is not None
                else None
            )
            beat["sfx_recommendations"] = _sfx_recommendations(
                beat["specification"]
            )
            is_search_target = bool(local_query and local_beat_id == beat["id"])
            beat["candidates"] = (
                []
                if is_search_target
                else self.list_candidates(workspace_id, beat["id"], limit=3)
                if include_candidates
                else []
            )
            beat["existing_search"] = self.search_existing_media(local_query) if is_search_target else []
            displayed = {
                item["asset_id"] for item in beat["candidates"] + beat["existing_search"]
            }
            beat["reuse"] = self._reuse_for_beat(
                reuse_groups, beat["id"], displayed_asset_ids=displayed
            )
            is_sfx_search_target = bool(sfx_query and sfx_beat_id == beat["id"])
            beat["sfx_candidates"] = (
                []
                if is_sfx_search_target
                else self.list_sfx_candidates(workspace_id, beat["id"], limit=3)
                if include_candidates
                else []
            )
            beat["sfx_search"] = (
                self.search_sfx_media(sfx_query) if is_sfx_search_target else []
            )
            sfx_displayed = {
                item["asset_id"] for item in beat["sfx_candidates"] + beat["sfx_search"]
            }
            beat["sfx_reuse"] = self._reuse_for_beat(
                sfx_reuse_groups, beat["id"], displayed_asset_ids=sfx_displayed
            )
        return result

    @staticmethod
    def _release_view(release: VideoRelease | None) -> dict[str, Any] | None:
        return (
            {
                "id": release.id,
                "name": release.name,
                "status": release.status,
                "release_date": release.release_date.isoformat() if release.release_date else None,
            }
            if release
            else None
        )

    def workspace_buckets(self, *, show_finished: bool = False) -> dict[str, list[dict[str, Any]]]:
        buckets = {"planned": [], "in_production": [], "completed": []}
        for workspace in self.list_workspaces():
            if workspace["status"] == "completed" and not show_finished:
                continue
            buckets[workspace["status"]].append(workspace)
        return buckets

    def list_releases(self, *, show_released: bool = True) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            releases = list(
                session.scalars(
                    select(VideoRelease).options(
                        selectinload(VideoRelease.workspaces).selectinload(ProducerWorkspace.beats),
                        selectinload(VideoRelease.presentation_revisions).selectinload(
                            ReleasePresentationRevision.thumbnail_asset
                        ),
                    )
                )
            )
            if not show_released:
                releases = [item for item in releases if item.status != "released"]
            releases.sort(key=self._release_sort_key)
            return [self._release_detail(release) for release in releases]

    def get_release(self, release_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            release = session.scalar(
                select(VideoRelease)
                .where(VideoRelease.id == release_id)
                .options(
                    selectinload(VideoRelease.workspaces).selectinload(ProducerWorkspace.beats),
                    selectinload(VideoRelease.presentation_revisions).selectinload(
                        ReleasePresentationRevision.thumbnail_asset
                    ),
                )
            )
            if release is None:
                raise ProducerWorkflowError("video release was not found")
            detail = self._release_detail(release)
            detail["history"] = self._event_views(session, "release", release.id)
            return detail

    @staticmethod
    def _release_sort_key(release: VideoRelease) -> tuple[Any, ...]:
        # Active dated releases are nearest first; active undated releases follow.
        # Released history is always last and is newest-first when dated.
        if release.status != "released":
            return (0, release.release_date is None, release.release_date or date.max, release.name.casefold())
        return (1, release.release_date is None, -(release.release_date.toordinal() if release.release_date else 0), release.name.casefold())

    @classmethod
    def _release_detail(cls, release: VideoRelease) -> dict[str, Any]:
        stories = sorted(release.workspaces, key=lambda item: (item.release_position or 999999, item.created_at, item.id))
        revisions = sorted(
            release.presentation_revisions,
            key=lambda item: (item.sequence, item.created_at, item.id),
            reverse=True,
        )
        return {
            "id": release.id,
            "name": release.name,
            "status": release.status,
            "release_date": release.release_date.isoformat() if release.release_date else None,
            "workspaces": [{"workspace_id": item.id, "title": item.title, "story_id": item.story_external_id, "status": item.status, "position": item.release_position, "selected": sum(1 for beat in item.beats if beat.selected_asset_id), "total": len(item.beats)} for item in stories],
            "presentation": cls._presentation_view(revisions[0]) if revisions else None,
            "presentation_history": [cls._presentation_view(item) for item in revisions],
        }

    @staticmethod
    def _presentation_view(revision: ReleasePresentationRevision) -> dict[str, Any]:
        thumbnail = revision.thumbnail_asset
        return {
            "id": revision.id,
            "sequence": revision.sequence,
            "public_title": revision.public_title,
            "description": revision.description,
            "thumbnail_asset_id": revision.thumbnail_asset_id,
            "thumbnail_title": thumbnail.title if thumbnail else None,
            "thumbnail_path": thumbnail.relative_path if thumbnail else None,
            "source": revision.source,
            "change_note": revision.change_note,
            "created_at": revision.created_at,
        }

    @staticmethod
    def _record_event(
        session: Session,
        subject_type: str,
        subject_id: str,
        event_type: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        related_subject_type: str | None = None,
        related_subject_id: str | None = None,
        source: str = "producer_ui",
    ) -> None:
        payload: dict[str, Any] = {}
        if before is not None:
            payload["before"] = before
        if after is not None:
            payload["after"] = after
        session.add(
            ProductionEvent(
                id=str(uuid.uuid4()),
                subject_type=subject_type,
                subject_id=subject_id,
                related_subject_type=related_subject_type,
                related_subject_id=related_subject_id,
                event_type=event_type,
                occurred_at=datetime.now(timezone.utc),
                source=source,
                payload_json=payload,
            )
        )

    @staticmethod
    def _event_views(
        session: Session, subject_type: str, subject_id: str, *, limit: int = 30
    ) -> list[dict[str, Any]]:
        events = list(
            session.scalars(
                select(ProductionEvent)
                .where(
                    ProductionEvent.subject_type == subject_type,
                    ProductionEvent.subject_id == subject_id,
                )
                .order_by(ProductionEvent.occurred_at.desc(), ProductionEvent.id.desc())
                .limit(limit)
            )
        )
        return [
            {
                "id": item.id,
                "event_type": item.event_type,
                "label": item.event_type.replace(".", " ").replace("_", " ").title(),
                "occurred_at": item.occurred_at,
                "source": item.source,
                "before": item.payload_json.get("before"),
                "after": item.payload_json.get("after"),
            }
            for item in events
        ]

    def create_release(self, name: str) -> dict[str, Any]:
        clean = name.strip()
        if not clean:
            raise ProducerWorkflowError("release name is required")
        with Session(self.engine) as session:
            if session.scalar(select(VideoRelease).where(func.lower(VideoRelease.name) == clean.casefold())):
                raise ProducerWorkflowError("a video release with that name already exists")
            release = VideoRelease(id=str(uuid.uuid4()), name=clean)
            session.add(release)
            self._record_event(
                session,
                "release",
                release.id,
                "release.created",
                after={"name": clean, "status": "planned", "release_date": None},
            )
            session.commit()
            return self._release_view(release) or {}

    def rename_release(self, release_id: str, name: str) -> None:
        clean = name.strip()
        if not clean: raise ProducerWorkflowError("release name is required")
        with Session(self.engine) as session:
            release = session.get(VideoRelease, release_id)
            if release is None: raise ProducerWorkflowError("video release was not found")
            duplicate = session.scalar(select(VideoRelease).where(func.lower(VideoRelease.name) == clean.casefold(), VideoRelease.id != release_id))
            if duplicate: raise ProducerWorkflowError("a video release with that name already exists")
            before = {"name": release.name}
            release.name = clean
            self._record_event(
                session, "release", release.id, "release.renamed", before=before,
                after={"name": clean},
            )
            session.commit()

    def update_release_metadata(
        self, release_id: str, *, status: str, release_date: str | None
    ) -> None:
        if status not in RELEASE_WORKSPACE_STATUS:
            raise ProducerWorkflowError("invalid video release status")
        try:
            parsed_date = date.fromisoformat(release_date) if release_date else None
        except ValueError as exc:
            raise ProducerWorkflowError("release date must be a valid date") from exc
        with Session(self.engine) as session:
            release = session.scalar(
                select(VideoRelease)
                .where(VideoRelease.id == release_id)
                .options(selectinload(VideoRelease.workspaces))
            )
            if release is None:
                raise ProducerWorkflowError("video release was not found")
            before = {
                "status": release.status,
                "release_date": release.release_date.isoformat() if release.release_date else None,
            }
            release.status = status
            release.release_date = parsed_date
            target_workspace_status = RELEASE_WORKSPACE_STATUS[status]
            for workspace in release.workspaces:
                if workspace.status != target_workspace_status:
                    old_status = workspace.status
                    workspace.status = target_workspace_status
                    self._record_event(
                        session,
                        "workspace",
                        workspace.id,
                        "workspace.status_changed",
                        before={"status": old_status},
                        after={"status": target_workspace_status},
                        related_subject_type="release",
                        related_subject_id=release.id,
                        source="release_status_sync",
                    )
            self._record_event(
                session,
                "release",
                release.id,
                "release.metadata_changed",
                before=before,
                after={
                    "status": status,
                    "release_date": parsed_date.isoformat() if parsed_date else None,
                },
            )
            session.commit()

    def delete_release(self, release_id: str) -> None:
        with Session(self.engine) as session:
            release = session.scalar(select(VideoRelease).where(VideoRelease.id == release_id).options(selectinload(VideoRelease.workspaces), selectinload(VideoRelease.presentation_revisions)))
            if release is None: raise ProducerWorkflowError("video release was not found")
            if release.workspaces: raise ProducerWorkflowError(f"Release still contains {len(release.workspaces)} workspaces. Unassign them before deleting the release.")
            if release.status != "planned":
                raise ProducerWorkflowError("only an unused planned release may be deleted")
            if release.presentation_revisions:
                raise ProducerWorkflowError("a release with public presentation history cannot be deleted")
            if session.scalar(select(ProductionEvent.id).where(ProductionEvent.subject_type == "release", ProductionEvent.subject_id == release.id, ProductionEvent.event_type == "release.workspace_assigned").limit(1)):
                raise ProducerWorkflowError("a release with story assignment history cannot be deleted")
            self._record_event(
                session, "release", release.id, "release.deleted",
                before={"name": release.name, "status": release.status, "release_date": None},
            )
            session.delete(release)
            session.commit()

    def update_workspace_status(self, workspace_id: str, status: str) -> None:
        if status not in {"planned", "in_production", "completed"}: raise ProducerWorkflowError("invalid workspace status")
        with Session(self.engine) as session:
            workspace = session.get(ProducerWorkspace, workspace_id)
            if workspace is None: raise ProducerWorkflowError("producer workspace was not found")
            if workspace.video_release_id:
                raise ProducerWorkflowError("workspace status is controlled by its assigned video release")
            before = {"status": workspace.status}
            workspace.status = status
            self._record_event(
                session, "workspace", workspace.id, "workspace.status_changed",
                before=before, after={"status": status},
            )
            session.commit()

    def rename_workspace_title(self, workspace_id: str, title: str) -> None:
        clean = title.strip()
        if not clean:
            raise ProducerWorkflowError("story title is required")
        with Session(self.engine) as session:
            workspace = session.get(ProducerWorkspace, workspace_id)
            if workspace is None:
                raise ProducerWorkflowError("producer workspace was not found")
            before = {"title": workspace.title}
            workspace.title = clean
            self._record_event(
                session, "workspace", workspace.id, "workspace.title_changed",
                before=before, after={"title": clean},
            )
            session.commit()

    def update_beat_requirements(
        self, workspace_id: str, beat_id: str, *, media_preference: str, source_requirement: str
    ) -> None:
        if media_preference not in {"image", "video", "either"}:
            raise ProducerWorkflowError("invalid media preference")
        if source_requirement not in {"representative", "exact"}:
            raise ProducerWorkflowError("invalid source requirement")
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            specification = dict(beat.specification_json)
            specification["media_preference"] = media_preference
            specification["source_requirement"] = source_requirement
            beat.specification_json = specification
            session.commit()

    def assign_workspace_release(self, workspace_id: str, release_id: str | None) -> None:
        with Session(self.engine) as session:
            workspace = session.get(ProducerWorkspace, workspace_id)
            if workspace is None: raise ProducerWorkflowError("producer workspace was not found")
            if not release_id:
                if workspace.video_release_id:
                    old_release_id = workspace.video_release_id
                    before = {
                        "video_release_id": old_release_id,
                        "release_position": workspace.release_position,
                    }
                    workspace.video_release_id = None
                    workspace.release_position = None
                    self._record_event(
                        session, "workspace", workspace.id, "workspace.release_unassigned",
                        before=before,
                        after={"video_release_id": None, "release_position": None},
                        related_subject_type="release", related_subject_id=old_release_id,
                    )
                    self._record_event(
                        session, "release", old_release_id, "release.workspace_unassigned",
                        before={**before, "workspace_id": workspace.id},
                        after={"workspace_id": workspace.id, "video_release_id": None, "release_position": None},
                        related_subject_type="workspace", related_subject_id=workspace.id,
                    )
                session.commit()
                return
            release = session.get(VideoRelease, release_id)
            if release is None: raise ProducerWorkflowError("video release was not found")
            if release.status == "released":
                raise ProducerWorkflowError("released video releases cannot accept story assignments")
            if workspace.video_release_id != release_id:
                old_release_id = workspace.video_release_id
                old_position = workspace.release_position
                if old_release_id:
                    self._record_event(
                        session, "release", old_release_id, "release.workspace_unassigned",
                        before={"workspace_id": workspace.id, "video_release_id": old_release_id, "release_position": old_position},
                        after={"workspace_id": workspace.id, "video_release_id": None, "release_position": None},
                        related_subject_type="workspace", related_subject_id=workspace.id,
                    )
                maximum = session.scalar(select(func.max(ProducerWorkspace.release_position)).where(ProducerWorkspace.video_release_id == release_id)) or 0
                new_position = maximum + 1
                workspace.video_release_id = release_id
                workspace.release_position = new_position
                self._record_event(
                    session, "workspace", workspace.id, "workspace.release_assigned",
                    before={"video_release_id": old_release_id, "release_position": old_position},
                    after={"video_release_id": release_id, "release_position": new_position},
                    related_subject_type="release", related_subject_id=release_id,
                )
                self._record_event(
                    session, "release", release_id, "release.workspace_assigned",
                    before={"workspace_id": workspace.id, "video_release_id": old_release_id, "release_position": old_position},
                    after={"workspace_id": workspace.id, "video_release_id": release_id, "release_position": new_position},
                    related_subject_type="workspace", related_subject_id=workspace.id,
                )
            target_status = RELEASE_WORKSPACE_STATUS[release.status]
            if workspace.status != target_status:
                old_status = workspace.status
                workspace.status = target_status
                self._record_event(
                    session, "workspace", workspace.id, "workspace.status_changed",
                    before={"status": old_status}, after={"status": target_status},
                    related_subject_type="release", related_subject_id=release.id,
                    source="release_assignment_sync",
                )
            session.commit()

    def move_workspace_release_position(self, workspace_id: str, direction: int) -> None:
        with Session(self.engine) as session:
            workspace = session.get(ProducerWorkspace, workspace_id)
            if workspace is None or not workspace.video_release_id: raise ProducerWorkflowError("workspace is not assigned to a video release")
            rows = list(session.scalars(select(ProducerWorkspace).where(ProducerWorkspace.video_release_id == workspace.video_release_id).order_by(ProducerWorkspace.release_position, ProducerWorkspace.created_at)))
            index = next(i for i, item in enumerate(rows) if item.id == workspace_id)
            target = index + direction
            if 0 <= target < len(rows): rows[index], rows[target] = rows[target], rows[index]
            before_order = [item.id for item in sorted(rows, key=lambda item: item.release_position or 999999)]
            for position, item in enumerate(rows, 1):
                if item.release_position != position:
                    old_position = item.release_position
                    item.release_position = position
                    self._record_event(
                        session, "workspace", item.id, "workspace.release_position_changed",
                        before={"release_position": old_position},
                        after={"release_position": position},
                        related_subject_type="release", related_subject_id=workspace.video_release_id,
                    )
            after_order = [item.id for item in rows]
            if before_order != after_order:
                self._record_event(
                    session, "release", workspace.video_release_id, "release.story_order_changed",
                    before={"workspace_ids": before_order}, after={"workspace_ids": after_order},
                    related_subject_type="workspace", related_subject_id=workspace.id,
                )
            session.commit()

    def delete_workspace(self, workspace_id: str) -> str:
        with Session(self.engine) as session:
            workspace = session.get(ProducerWorkspace, workspace_id)
            if workspace is None: raise ProducerWorkflowError("producer workspace was not found")
            if workspace.video_release_id:
                raise ProducerWorkflowError("unassign the workspace from its video release before deleting it")
            if workspace.status == "completed":
                raise ProducerWorkflowError("completed workspaces are retained as production history")
            if session.scalar(select(ProductionEvent.id).where(ProductionEvent.subject_type == "workspace", ProductionEvent.subject_id == workspace.id, ProductionEvent.event_type == "workspace.release_assigned").limit(1)):
                raise ProducerWorkflowError("a workspace with release assignment history is retained as production history")
            story_id = workspace.story_external_id
        projects_root = (self.settings.root / "Projects").resolve()
        target = (projects_root / story_id).resolve()
        if target == projects_root or projects_root not in target.parents: raise ProducerWorkflowError("workspace project path is unsafe")
        try:
            if target.exists(): shutil.rmtree(target)
        except OSError as exc:
            raise ProducerWorkflowError("workspace project files could not be deleted; the workspace was kept") from exc
        with Session(self.engine) as session:
            workspace = session.get(ProducerWorkspace, workspace_id)
            if workspace is None: raise ProducerWorkflowError("producer workspace was not found")
            self._record_event(
                session, "workspace", workspace.id, "workspace.deleted",
                before={
                    "story_id": workspace.story_external_id,
                    "title": workspace.title,
                    "status": workspace.status,
                    "video_release_id": None,
                    "release_position": None,
                },
            )
            session.delete(workspace)
            session.commit()
        return story_id

    def list_thumbnail_candidates(self, *, limit: int = 100) -> list[dict[str, Any]]:
        response = self.catalog.search_media(
            SearchMediaRequest(
                query="", media_type="image", availability="available", limit=limit
            )
        )
        return [
            {
                "asset_id": item.asset_id,
                "title": self.catalog.get_asset_detail(item.asset_id).title,
                "relative_path": item.relative_path,
            }
            for item in response.candidates
        ]

    def create_release_presentation(
        self,
        release_id: str,
        *,
        public_title: str,
        description: str | None,
        thumbnail_asset_id: int | None,
        change_note: str | None = None,
    ) -> dict[str, Any]:
        return self.revise_release_presentation(
            release_id,
            public_title=public_title,
            description=description,
            thumbnail_asset_id=thumbnail_asset_id,
            change_note=change_note,
        )

    def revise_release_presentation(
        self,
        release_id: str,
        *,
        public_title: str | object = _PRESENTATION_UNSET,
        description: str | None | object = _PRESENTATION_UNSET,
        thumbnail_asset_id: int | None | object = _PRESENTATION_UNSET,
        change_note: str | None = None,
    ) -> dict[str, Any]:
        clean_note = change_note.strip() if change_note and change_note.strip() else None
        with Session(self.engine) as session:
            release = session.scalar(
                select(VideoRelease)
                .where(VideoRelease.id == release_id)
                .options(
                    selectinload(VideoRelease.presentation_revisions).selectinload(
                        ReleasePresentationRevision.thumbnail_asset
                    )
                )
            )
            if release is None:
                raise ProducerWorkflowError("video release was not found")
            revisions = sorted(release.presentation_revisions, key=lambda item: item.sequence)
            previous = self._presentation_view(revisions[-1]) if revisions else None
            previous_title = previous["public_title"] if previous else None
            previous_description = previous["description"] if previous else None
            previous_thumbnail_id = previous["thumbnail_asset_id"] if previous else None
            title = (
                public_title.strip()
                if public_title is not _PRESENTATION_UNSET
                else previous_title
            )
            clean_description = (
                description.strip() or None
                if description is not _PRESENTATION_UNSET and isinstance(description, str)
                else previous_description
            )
            selected_thumbnail_id = (
                thumbnail_asset_id
                if thumbnail_asset_id is not _PRESENTATION_UNSET
                else previous_thumbnail_id
            )
            if not isinstance(title, str) or not title:
                raise ProducerWorkflowError("set a public title before editing the thumbnail or description")
            if selected_thumbnail_id is not None and not isinstance(selected_thumbnail_id, int):
                raise ProducerWorkflowError("thumbnail asset ID must be a number")
            if selected_thumbnail_id is not None:
                try:
                    thumbnail_detail = self.catalog.get_asset_detail(selected_thumbnail_id)
                except MediaServiceError as exc:
                    raise ProducerWorkflowError("thumbnail image asset was not found") from exc
                if thumbnail_detail.media_type != "image" or not thumbnail_detail.available:
                    raise ProducerWorkflowError("thumbnail must be an existing available image asset")
            sequence = revisions[-1].sequence + 1 if revisions else 1
            revision = ReleasePresentationRevision(
                id=str(uuid.uuid4()),
                video_release_id=release.id,
                sequence=sequence,
                public_title=title,
                description=clean_description,
                thumbnail_asset_id=selected_thumbnail_id,
                source="producer_ui",
                change_note=clean_note,
            )
            session.add(revision)
            self._record_event(
                session,
                "release",
                release.id,
                "release.presentation_revised",
                before=self._presentation_event_state(previous),
                after={
                    "revision_id": revision.id,
                    "sequence": sequence,
                    "public_title": title,
                    "description": clean_description,
                    "thumbnail_asset_id": selected_thumbnail_id,
                    "change_note": clean_note,
                },
            )
            session.commit()
            return {
                "id": revision.id,
                "sequence": revision.sequence,
                "public_title": revision.public_title,
                "description": revision.description,
                "thumbnail_asset_id": revision.thumbnail_asset_id,
                "change_note": revision.change_note,
            }

    def import_release_thumbnail_upload(
        self, release_id: str, temporary_path: Path, original_filename: str
    ) -> dict[str, Any]:
        release = self.get_release(release_id)
        if release["presentation"] is None:
            raise ProducerWorkflowError("set a public title before adding a thumbnail")
        media_type, maximum = self._upload_media_type(original_filename)
        if media_type != "image":
            raise ProducerWorkflowError("a thumbnail upload must be an image")
        outcome = self._ingest_upload(
            temporary_path, original_filename, media_type=media_type, maximum=maximum
        )
        presentation = self.revise_release_presentation(
            release_id,
            thumbnail_asset_id=outcome["asset_id"],
            change_note="Uploaded thumbnail selected",
        )
        return {**outcome, "presentation_revision": presentation["sequence"]}

    @staticmethod
    def _presentation_event_state(presentation: dict[str, Any] | None) -> dict[str, Any] | None:
        if presentation is None:
            return None
        return {
            "revision_id": presentation["id"],
            "sequence": presentation["sequence"],
            "public_title": presentation["public_title"],
            "description": presentation["description"],
            "thumbnail_asset_id": presentation["thumbnail_asset_id"],
            "change_note": presentation["change_note"],
        }

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

    def search_existing_media(self, query: str, *, limit: int = 12) -> list[dict[str, Any]]:
        response = self.catalog.search_media(
            SearchMediaRequest(query=query.strip(), media_type=None, limit=limit)
        )
        return [
            self._candidate_view(item, self.catalog.get_asset_detail(item.asset_id))
            for item in response.candidates
        ]

    def list_sfx_candidates(
        self, workspace_id: str, beat_id: str, *, limit: int = 3
    ) -> list[dict[str, Any]]:
        beat, _hidden = self._load_beat(workspace_id, beat_id)
        recommendations = _sfx_recommendations(beat.specification_json)
        merged: list[SearchCandidateResult] = []
        seen: set[int] = set()
        for recommendation in recommendations:
            for query in recommendation.get("search_queries", []):
                response = self.catalog.search_media(
                    SearchMediaRequest(query=query, media_type="audio", limit=20)
                )
                for candidate in response.candidates:
                    if candidate.asset_id in seen:
                        continue
                    seen.add(candidate.asset_id)
                    merged.append(candidate)
                    if len(merged) >= limit:
                        break
                if len(merged) >= limit:
                    break
            if len(merged) >= limit:
                break
        return [
            self._candidate_view(item, self.catalog.get_asset_detail(item.asset_id))
            for item in merged
        ]

    def search_sfx_media(self, query: str, *, limit: int = 12) -> list[dict[str, Any]]:
        response = self.catalog.search_media(
            SearchMediaRequest(query=query.strip(), media_type="audio", limit=limit)
        )
        return [
            self._candidate_view(item, self.catalog.get_asset_detail(item.asset_id))
            for item in response.candidates
        ]

    def _reuse_groups(
        self, workspace_id: str, release: dict[str, Any] | None
    ) -> dict[str, list[dict[str, Any]]]:
        with Session(self.engine) as session:
            rows = list(
                session.execute(
                    select(ProducerBeat, ProducerWorkspace)
                    .join(ProducerWorkspace, ProducerBeat.workspace_id == ProducerWorkspace.id)
                    .where(ProducerBeat.selected_asset_id.is_not(None))
                    .order_by(ProducerBeat.selected_at.desc(), ProducerBeat.updated_at.desc())
                )
            )
        contexts: dict[int, list[dict[str, Any]]] = {}
        recent_ids: list[int] = []
        story_ids: list[int] = []
        release_ids: list[int] = []
        for beat, workspace in rows:
            asset_id = beat.selected_asset_id
            if asset_id is None:
                continue
            context = {
                "beat_db_id": beat.id,
                "beat_id": beat.external_beat_id,
                "story_id": workspace.story_external_id,
                "story_title": workspace.title,
            }
            contexts.setdefault(asset_id, []).append(context)
            if asset_id not in recent_ids:
                recent_ids.append(asset_id)
            if workspace.id == workspace_id and asset_id not in story_ids:
                story_ids.append(asset_id)
            if release and workspace.video_release_id == release["id"] and workspace.id != workspace_id and asset_id not in release_ids:
                release_ids.append(asset_id)

        def views(asset_ids: list[int], limit: int = 6) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for asset_id in asset_ids[:limit]:
                view = self._asset_view(self.catalog.get_asset_detail(asset_id))
                view["used_in"] = contexts[asset_id]
                result.append(view)
            return result

        return {"recent": views(recent_ids), "story": views(story_ids), "release": views(release_ids)}

    def _sfx_reuse_groups(
        self, workspace_id: str, release: dict[str, Any] | None
    ) -> dict[str, list[dict[str, Any]]]:
        with Session(self.engine) as session:
            rows = list(
                session.execute(
                    select(ProducerBeat, ProducerWorkspace)
                    .join(ProducerWorkspace, ProducerBeat.workspace_id == ProducerWorkspace.id)
                    .where(ProducerBeat.selected_sfx_asset_id.is_not(None))
                    .order_by(ProducerBeat.selected_sfx_at.desc(), ProducerBeat.updated_at.desc())
                )
            )
        contexts: dict[int, list[dict[str, Any]]] = {}
        recent_ids: list[int] = []
        story_ids: list[int] = []
        release_ids: list[int] = []
        for beat, workspace in rows:
            asset_id = beat.selected_sfx_asset_id
            if asset_id is None:
                continue
            contexts.setdefault(asset_id, []).append({
                "beat_db_id": beat.id,
                "beat_id": beat.external_beat_id,
                "story_id": workspace.story_external_id,
                "story_title": workspace.title,
            })
            if asset_id not in recent_ids:
                recent_ids.append(asset_id)
            if workspace.id == workspace_id and asset_id not in story_ids:
                story_ids.append(asset_id)
            if release and workspace.video_release_id == release["id"] and workspace.id != workspace_id and asset_id not in release_ids:
                release_ids.append(asset_id)

        def views(asset_ids: list[int], limit: int = 6) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for asset_id in asset_ids[:limit]:
                view = self._asset_view(self.catalog.get_asset_detail(asset_id))
                view["used_in"] = contexts[asset_id]
                result.append(view)
            return result

        return {"recent": views(recent_ids), "story": views(story_ids), "release": views(release_ids)}

    @staticmethod
    def _reuse_for_beat(
        groups: dict[str, list[dict[str, Any]]], beat_id: str, *, displayed_asset_ids: set[int]
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        seen = set(displayed_asset_ids)
        for group in ("release", "story", "recent"):
            result[group] = []
            for asset in groups[group]:
                contexts = [item for item in asset["used_in"] if item["beat_db_id"] != beat_id]
                if not contexts or asset["asset_id"] in seen:
                    continue
                result[group].append({**asset, "used_in": contexts})
                seen.add(asset["asset_id"])
        return result

    def select_asset(
        self,
        workspace_id: str,
        beat_id: str,
        asset_id: int,
        *,
        rebuild_edit: bool = True,
        override_media_preference: bool = False,
    ) -> None:
        detail = self.catalog.get_asset_detail(asset_id)
        if not detail.available or not detail.sha256:
            raise ProducerWorkflowError("the selected asset is not locally available")
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            preference = beat.specification_json["media_preference"]
            if preference != "either" and detail.media_type != preference:
                if not override_media_preference:
                    raise ProducerWorkflowError(
                        f"This beat currently prefers an {preference}, but the selected asset is a {detail.media_type}. "
                        f"Change the beat requirement below or choose ‘Use & set {detail.media_type}’."
                    )
                specification = dict(beat.specification_json)
                specification["media_preference"] = detail.media_type
                beat.specification_json = specification
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

    def select_sfx(
        self, workspace_id: str, beat_id: str, asset_id: int, *, rebuild_edit: bool = True
    ) -> None:
        detail = self.catalog.get_asset_detail(asset_id)
        if detail.media_type != "audio":
            raise ProducerWorkflowError("the selected SFX must be an audio asset")
        if not detail.available or not detail.sha256:
            raise ProducerWorkflowError("the selected SFX is not locally available")
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            beat.selected_sfx_asset_id = detail.asset_id
            beat.selected_sfx_asset_sha256 = detail.sha256
            beat.selected_sfx_at = datetime.now(timezone.utc)
            session.commit()
        if rebuild_edit:
            self.build_edit_folder(workspace_id)

    def clear_sfx_selection(
        self, workspace_id: str, beat_id: str, *, rebuild_edit: bool = True
    ) -> None:
        with Session(self.engine) as session:
            beat = self._session_beat(session, workspace_id, beat_id)
            beat.selected_sfx_asset_id = None
            beat.selected_sfx_asset_sha256 = None
            beat.selected_sfx_at = None
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
        *,
        media_role: str = "visual",
        sfx_kind: str | None = None,
    ) -> dict[str, Any]:
        media_type, maximum = self._upload_media_type(original_filename)
        if media_role == "sfx":
            if media_type != "audio":
                raise ProducerWorkflowError("an SFX upload must be WAV, MP3, or FLAC audio")
            _validate_sfx_kind(sfx_kind)
        elif media_type == "audio":
            raise ProducerWorkflowError("audio files must be imported from the SFX section")
        else:
            self._ensure_preference(workspace_id, beat_id, media_type)
        outcome = self._ingest_upload(
            temporary_path,
            original_filename,
            media_type=media_type,
            maximum=maximum,
            sfx_kind=sfx_kind,
        )
        if media_role == "sfx":
            self.select_sfx(workspace_id, beat_id, outcome["asset_id"])
        else:
            self.select_asset(workspace_id, beat_id, outcome["asset_id"])
        return outcome

    def _upload_media_type(self, original_filename: str) -> tuple[str, int]:
        extension = Path(original_filename).suffix.lower()
        if extension in IMAGE_EXTENSIONS:
            return "image", self.settings.max_image_download_bytes
        if extension in VIDEO_EXTENSIONS:
            return "video", self.settings.max_video_download_bytes
        if extension in AUDIO_EXTENSIONS:
            return "audio", self.settings.max_audio_download_bytes
        raise ProducerWorkflowError("unsupported upload file type")

    def _ingest_upload(
        self,
        temporary_path: Path,
        original_filename: str,
        *,
        media_type: str,
        maximum: int,
        sfx_kind: str | None = None,
    ) -> dict[str, Any]:
        extension = Path(original_filename).suffix.lower()
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
                {"image": "Images", "video": "Videos", "audio": "SFX"}[media_type]
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
            if media_type == "audio" and sfx_kind:
                asset.sfx_kind = sfx_kind
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
        media_role: str = "visual",
        sfx_kind: str | None = None,
        source_name: str | None = None,
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
        elif extension in AUDIO_EXTENSIONS:
            media_type = "audio"
        elif extension in {".gif", ".svg"}:
            raise ProducerWorkflowError(
                "Unsupported media URL type. GIF and SVG are not supported."
            )
        else:
            raise ProducerWorkflowError(
                "This URL did not resolve to a supported media file. "
                "Provide a direct WAV, MP3, FLAC, image, or video URL."
            )
        if media_role == "sfx":
            if media_type != "audio":
                raise ProducerWorkflowError("an SFX import must resolve to WAV, MP3, or FLAC audio")
            _validate_sfx_kind(sfx_kind)
        elif media_type == "audio":
            raise ProducerWorkflowError("audio files must be imported from the SFX section")
        else:
            self._ensure_preference(workspace_id, beat_id, media_type)

        creator = (creator_attribution or (resolved.creator_attribution if resolved else "") or "").strip() or None
        supplied_license_name = (license_name or (resolved.license_name if resolved else "") or "").strip()
        provider_name = (source_name or "manual_external").strip()[:100] or "manual_external"
        result = MediaSearchResult(
            provider=provider_name,
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
                "invalid_audio",
            }:
                raise ProducerWorkflowError(
                    "This URL did not resolve to a supported media file. "
                    "Provide a supported direct media URL."
                ) from exc
            raise ProducerWorkflowError(str(exc)) from exc
        finally:
            acquisition.close()
        if media_type == "audio" and sfx_kind:
            with Session(self.engine) as session:
                asset = session.get(MediaAsset, outcome.asset_id)
                if asset is not None:
                    asset.sfx_kind = sfx_kind
                    session.commit()
        if media_role == "sfx":
            self.select_sfx(workspace_id, beat_id, outcome.asset_id)
        else:
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
        staging_sfx = staging / "SFX"
        staging_visuals.mkdir(parents=True)
        staging_sfx.mkdir(parents=True)
        rows: list[dict[str, Any]] = []
        max_sequence = max((beat["sequence"] for beat in workspace["beats"]), default=1)
        prefix_width = max(3, len(str(max_sequence)))

        def stage_sfx(beat: dict[str, Any]) -> dict[str, Any] | None:
            selected_sfx = beat["selected_sfx"]
            if selected_sfx is None:
                return None
            source_path = self.settings.root / selected_sfx["current_location"]
            if not source_path.is_file():
                raise ProducerWorkflowError(
                    f"selected SFX for {beat['beat_id']} is missing"
                )
            recommendations = beat["sfx_recommendations"]
            desired_sound = recommendations[0].get("desired_sound") if recommendations else None
            label = _safe_label(desired_sound or "sfx", fallback=beat["beat_id"])
            filename = (
                f"{beat['sequence']:0{prefix_width}d}-sfx-{label[:56]}"
                f"{source_path.suffix.lower()}"
            )
            destination = staging_sfx / filename
            mode = "hardlink"
            try:
                linker(source_path, destination)
            except OSError:
                copier(source_path, destination)
                mode = "copy"
            source = selected_sfx["source"]
            license_record = selected_sfx["license"]
            return {
                "sequence": beat["sequence"], "beat_id": beat["beat_id"],
                "filename": filename, "asset_id": selected_sfx["asset_id"],
                "media_type": "audio",
                "source_provider": source["provider"] or source["origin"],
                "source_url": source["source_url"] or "",
                "creator": source["creator_name"] or "",
                "license_status": license_record["status"],
                "license_name": license_record["name"] or "",
                "transfer_mode": mode, "media_role": "sfx",
                "edit_path": f"SFX/{filename}",
                "sfx_kind": selected_sfx["sfx_kind"] or "",
            }

        try:
            for beat in workspace["beats"]:
                selected = beat["selected"]
                if selected is None:
                    sfx_row = stage_sfx(beat)
                    if sfx_row:
                        rows.append(sfx_row)
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
                        "media_role": "visual",
                        "edit_path": f"Visuals/{filename}",
                        "sfx_kind": "",
                    }
                )
                sfx_row = stage_sfx(beat)
                if sfx_row:
                    rows.append(sfx_row)
            manifest = staging / "manifest.csv"
            with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
                fieldnames = [
                    "sequence", "beat_id", "filename", "asset_id", "media_type",
                    "source_provider", "source_url", "creator", "license_status",
                    "license_name", "transfer_mode", "media_role", "edit_path", "sfx_kind",
                ]
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)

            edit_root.mkdir(parents=True, exist_ok=True)
            visuals = edit_root / "Visuals"
            sfx = edit_root / "SFX"
            _assert_within(visuals, edit_root)
            _assert_within(sfx, edit_root)
            if visuals.exists():
                shutil.rmtree(visuals)
            shutil.move(str(staging_visuals), str(visuals))
            if sfx.exists():
                shutil.rmtree(sfx)
            shutil.move(str(staging_sfx), str(sfx))
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
            "sfx_kind": detail.sfx_kind,
            "title": detail.title,
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


def _sfx_recommendations(specification: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only Project-supplied SFX guidance; never infer from beat text."""
    recommendations: list[dict[str, Any]] = []
    for opportunity in specification.get("production_opportunities", []):
        structured = opportunity.get("sfx_recommendation")
        if isinstance(structured, dict):
            recommendations.append({"trigger": opportunity.get("trigger"), **structured})
        elif opportunity.get("sfx_suggestion"):
            # Historical v1 plans remain visible, but missing structured fields are
            # intentionally not invented by the application.
            recommendations.append({
                "trigger": opportunity.get("trigger"),
                "desired_sound": opportunity["sfx_suggestion"],
                "legacy": True,
                "search_queries": [],
            })
    return recommendations


def _validate_sfx_kind(value: str | None) -> None:
    if value not in {"one_shot", "ambient"}:
        raise ProducerWorkflowError("choose whether the SFX is a one-shot or ambient sound")


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
