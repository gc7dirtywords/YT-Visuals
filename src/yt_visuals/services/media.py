from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath

from sqlalchemy import Engine, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from ..models import (
    AssetUsage,
    MediaAsset,
    MediaLocation,
    MediaProvider,
    MediaSource,
    Project,
    Story,
    Tag,
)
from .errors import (
    AssetNotFoundError,
    AssetUnavailableError,
    CatalogDatabaseError,
    InvalidFilterError,
    InvalidUsageReferenceError,
)
from .schemas import (
    AssetDetailResult,
    LibraryStatusResult,
    LicenseResult,
    MediaLocationResult,
    MediaSourceResult,
    RecentUsageRequest,
    RecentUsageResult,
    RecordUsageRequest,
    RecordUsageResult,
    SearchCandidateResult,
    SearchMediaRequest,
    SearchMediaResult,
    UsageResult,
)


class MediaCatalogService:
    """Stable application boundary for catalog reads and usage writes."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def search_media(self, request: SearchMediaRequest) -> SearchMediaResult:
        try:
            with Session(self.engine) as session:
                self._validate_search_context(session, request)
                statement = select(MediaAsset).options(*_asset_summary_loaders())
                statement = _apply_search_filters(statement, request)
                assets = list(session.scalars(statement))
                tokens = tuple(token for token in request.query.casefold().split() if token)
                if tokens:
                    assets = [asset for asset in assets if _matches_all_tokens(asset, tokens)]
                scored = [self._candidate(asset, request, tokens) for asset in assets]
                scored.sort(
                    key=lambda item: (
                        -item.score,
                        item.usage_count,
                        _datetime_sort(item.last_used_at),
                        item.relative_path.casefold(),
                        item.asset_id,
                    )
                )
                ranked = tuple(
                    item.model_copy(update={"rank": rank})
                    for rank, item in enumerate(scored[: request.limit], start=1)
                )
                return SearchMediaResult(
                    query=request.query, returned=len(ranked), candidates=ranked
                )
        except (InvalidFilterError, InvalidUsageReferenceError):
            raise
        except SQLAlchemyError as exc:
            raise CatalogDatabaseError("Catalog search failed", operation="search_media") from exc

    def get_asset_detail(self, asset_id: int, *, recent_usage_limit: int = 20) -> AssetDetailResult:
        if asset_id <= 0:
            raise AssetNotFoundError("Asset was not found", asset_id=asset_id)
        if not 1 <= recent_usage_limit <= 500:
            raise InvalidFilterError(
                "recent_usage_limit must be between 1 and 500", field="recent_usage_limit"
            )
        try:
            with Session(self.engine) as session:
                asset = session.scalar(
                    select(MediaAsset)
                    .where(MediaAsset.id == asset_id)
                    .options(*_asset_detail_loaders())
                )
                if asset is None:
                    raise AssetNotFoundError("Asset was not found", asset_id=asset_id)
                usages = sorted(asset.usages, key=lambda usage: usage.used_at, reverse=True)
                locations = tuple(
                    _location_result(item)
                    for item in sorted(asset.locations, key=lambda item: item.relative_path.casefold())
                )
                sources = tuple(
                    _source_result(item)
                    for item in sorted(
                        asset.sources,
                        key=lambda item: (
                            item.provider.name.casefold() if item.provider else "",
                            item.provider_asset_id or "",
                        ),
                    )
                )
                available = _asset_available(asset)
                seen = [item.first_seen_at for item in asset.locations]
                last_seen = [item.last_seen_at for item in asset.locations]
                return AssetDetailResult(
                    asset_id=asset.id,
                    relative_path=asset.relative_path,
                    current_location=_current_location(asset),
                    media_type=asset.media_type,
                    mime_type=asset.mime_type,
                    extension=PurePosixPath(asset.relative_path).suffix.lower(),
                    width=asset.width,
                    height=asset.height,
                    orientation=_orientation(asset.width, asset.height),
                    duration_ms=asset.duration_ms,
                    file_size_bytes=asset.file_size_bytes,
                    sha256=asset.sha256,
                    status=asset.status,
                    available=available,
                    title=asset.title,
                    description=asset.description,
                    imported_at=asset.imported_at,
                    first_seen_at=min(seen) if seen else None,
                    last_seen_at=max(last_seen) if last_seen else None,
                    locations=locations,
                    sources=sources,
                    license=_license_result(asset.license) if asset.license else None,
                    tags=tuple(sorted(tag.name for tag in asset.tags)),
                    usage_count=asset.usage_count,
                    last_used_at=asset.last_used_at,
                    recent_usage=tuple(
                        _usage_result(usage) for usage in usages[:recent_usage_limit]
                    ),
                    technical_metadata=asset.technical_metadata,
                )
        except AssetNotFoundError:
            raise
        except SQLAlchemyError as exc:
            raise CatalogDatabaseError(
                "Asset detail lookup failed", operation="get_asset_detail", asset_id=asset_id
            ) from exc

    def get_library_status(self, *, recent_window_days: int = 30) -> LibraryStatusResult:
        if not 1 <= recent_window_days <= 3650:
            raise InvalidFilterError(
                "recent_window_days must be between 1 and 3650", field="recent_window_days"
            )
        cutoff = _utcnow() - timedelta(days=recent_window_days)
        try:
            with Session(self.engine) as session:
                counts = dict(
                    session.execute(
                        select(MediaLocation.media_asset_id, func.count(MediaLocation.id))
                        .where(MediaLocation.status == "available")
                        .group_by(MediaLocation.media_asset_id)
                    ).all()
                )
                scalar_count = lambda statement: session.scalar(statement) or 0
                return LibraryStatusResult(
                    total_assets=scalar_count(select(func.count()).select_from(MediaAsset)),
                    available_assets=scalar_count(
                        select(func.count()).select_from(MediaAsset).where(MediaAsset.status == "active")
                    ),
                    missing_assets=scalar_count(
                        select(func.count()).select_from(MediaAsset).where(MediaAsset.status == "missing")
                    ),
                    images=scalar_count(
                        select(func.count()).select_from(MediaAsset).where(MediaAsset.media_type == "image")
                    ),
                    videos=scalar_count(
                        select(func.count()).select_from(MediaAsset).where(MediaAsset.media_type == "video")
                    ),
                    available_locations=sum(counts.values()),
                    missing_locations=scalar_count(
                        select(func.count()).select_from(MediaLocation).where(MediaLocation.status == "missing")
                    ),
                    duplicate_physical_locations=sum(max(0, count - 1) for count in counts.values()),
                    local_import_locations=scalar_count(
                        select(func.count()).select_from(MediaLocation).where(
                            MediaLocation.provenance_type == "local_import"
                        )
                    ),
                    provider_download_locations=scalar_count(
                        select(func.count()).select_from(MediaLocation).where(
                            MediaLocation.provenance_type == "provider_download"
                        )
                    ),
                    unused_assets=scalar_count(
                        select(func.count()).select_from(MediaAsset).where(MediaAsset.usage_count == 0)
                    ),
                    recently_used_assets=scalar_count(
                        select(func.count()).select_from(MediaAsset).where(MediaAsset.last_used_at >= cutoff)
                    ),
                    total_available_bytes=scalar_count(
                        select(func.coalesce(func.sum(MediaLocation.file_size_bytes), 0)).where(
                            MediaLocation.status == "available"
                        )
                    ),
                    recent_window_days=recent_window_days,
                    last_scan_at=None,
                    last_scan_status=None,
                )
        except InvalidFilterError:
            raise
        except SQLAlchemyError as exc:
            raise CatalogDatabaseError(
                "Library status lookup failed", operation="get_library_status"
            ) from exc

    def get_recent_usage(self, request: RecentUsageRequest) -> RecentUsageResult:
        try:
            with Session(self.engine) as session:
                statement = select(AssetUsage).options(*_usage_loaders())
                if request.asset_id is not None:
                    statement = statement.where(AssetUsage.asset_id == request.asset_id)
                if request.story_id is not None:
                    statement = statement.where(AssetUsage.story_id == request.story_id)
                if request.project_id is not None:
                    statement = statement.where(_usage_project_clause(request.project_id))
                if request.used_from is not None:
                    statement = statement.where(AssetUsage.used_at >= request.used_from)
                if request.used_to is not None:
                    statement = statement.where(AssetUsage.used_at <= request.used_to)
                statement = statement.order_by(AssetUsage.used_at.desc(), AssetUsage.id.desc()).limit(
                    request.limit
                )
                usages = tuple(_usage_result(item) for item in session.scalars(statement))
                return RecentUsageResult(returned=len(usages), usages=usages)
        except SQLAlchemyError as exc:
            raise CatalogDatabaseError(
                "Usage history lookup failed", operation="get_recent_usage"
            ) from exc

    def record_usage(self, request: RecordUsageRequest) -> RecordUsageResult:
        try:
            with Session(self.engine) as session:
                existing = session.scalar(
                    select(AssetUsage)
                    .where(AssetUsage.idempotency_key == request.idempotency_key)
                    .options(*_usage_loaders())
                )
                if existing is not None:
                    self._validate_retry(existing, request)
                    return self._record_result(session, existing, created=False)

                asset = session.get(MediaAsset, request.asset_id)
                if asset is None:
                    raise AssetNotFoundError("Asset was not found", asset_id=request.asset_id)
                if not request.allow_missing and not _asset_available(asset):
                    raise AssetUnavailableError(
                        "Asset is not locally available", asset_id=request.asset_id
                    )
                project, story = self._resolve_usage_context(session, request)
                usage = AssetUsage(
                    asset=asset,
                    project=project,
                    story=story,
                    usage_reference=request.usage_reference,
                    segment_label=request.segment_label,
                    narration_start_ms=request.narration_start_ms,
                    narration_end_ms=request.narration_end_ms,
                    usage_role=request.usage_role,
                    used_at=request.used_at or _utcnow(),
                    notes=request.notes,
                    idempotency_key=request.idempotency_key,
                )
                session.add(usage)
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    existing = session.scalar(
                        select(AssetUsage)
                        .where(AssetUsage.idempotency_key == request.idempotency_key)
                        .options(*_usage_loaders())
                    )
                    if existing is None:
                        raise
                    self._validate_retry(existing, request)
                    return self._record_result(session, existing, created=False)
                return self._record_result(session, usage, created=True)
        except (
            AssetNotFoundError,
            AssetUnavailableError,
            InvalidUsageReferenceError,
        ):
            raise
        except SQLAlchemyError as exc:
            raise CatalogDatabaseError("Usage recording failed", operation="record_usage") from exc

    @staticmethod
    def _validate_search_context(session: Session, request: SearchMediaRequest) -> None:
        if request.story_id is None:
            return
        story = session.get(Story, request.story_id)
        if story is None:
            raise InvalidFilterError("Story was not found", story_id=request.story_id)
        if request.project_id is not None and story.project_id != request.project_id:
            raise InvalidFilterError(
                "Story does not belong to the requested project",
                story_id=request.story_id,
                project_id=request.project_id,
            )

    @staticmethod
    def _resolve_usage_context(
        session: Session, request: RecordUsageRequest
    ) -> tuple[Project | None, Story | None]:
        story = session.get(Story, request.story_id) if request.story_id else None
        if request.story_id and story is None:
            raise InvalidUsageReferenceError("Story was not found", story_id=request.story_id)
        derived_project_id = story.project_id if story else request.project_id
        if story and request.project_id and story.project_id != request.project_id:
            raise InvalidUsageReferenceError(
                "Story does not belong to the requested project",
                story_id=story.id,
                project_id=request.project_id,
            )
        project = session.get(Project, derived_project_id) if derived_project_id else None
        if derived_project_id and project is None:
            raise InvalidUsageReferenceError("Project was not found", project_id=derived_project_id)
        return project, story

    @staticmethod
    def _validate_retry(existing: AssetUsage, request: RecordUsageRequest) -> None:
        comparable = (
            existing.asset_id == request.asset_id,
            existing.project_id == request.project_id
            or (request.project_id is None and existing.story_id == request.story_id),
            existing.story_id == request.story_id,
            existing.usage_reference == request.usage_reference,
            existing.segment_label == request.segment_label,
            existing.narration_start_ms == request.narration_start_ms,
            existing.narration_end_ms == request.narration_end_ms,
            existing.usage_role == request.usage_role,
            existing.notes == request.notes,
            request.used_at is None or _same_datetime(existing.used_at, request.used_at),
        )
        if not all(comparable):
            raise InvalidUsageReferenceError(
                "Idempotency key was already used for a different usage record",
                idempotency_key=request.idempotency_key,
            )

    @staticmethod
    def _record_result(
        session: Session, usage: AssetUsage, *, created: bool
    ) -> RecordUsageResult:
        session.refresh(usage.asset)
        return RecordUsageResult(
            created=created,
            usage=_usage_result(usage),
            asset_usage_count=usage.asset.usage_count,
            asset_last_used_at=usage.asset.last_used_at,
        )

    @staticmethod
    def _candidate(
        asset: MediaAsset, request: SearchMediaRequest, tokens: tuple[str, ...]
    ) -> SearchCandidateResult:
        recent_cutoff = _utcnow() - timedelta(days=30)
        recent_count = sum(1 for usage in asset.usages if _as_utc(usage.used_at) >= recent_cutoff)
        score, reasons = _rank_asset(asset, request, tokens, recent_count)
        return SearchCandidateResult(
            rank=0,
            score=score,
            score_reasons=tuple(reasons),
            asset_id=asset.id,
            relative_path=asset.relative_path,
            current_location=_current_location(asset),
            media_type=asset.media_type,
            mime_type=asset.mime_type,
            extension=PurePosixPath(asset.relative_path).suffix.lower(),
            width=asset.width,
            height=asset.height,
            orientation=_orientation(asset.width, asset.height),
            duration_ms=asset.duration_ms,
            file_size_bytes=asset.file_size_bytes,
            sha256=asset.sha256,
            available=_asset_available(asset),
            locations=tuple(sorted(item.relative_path for item in asset.locations)),
            providers=tuple(sorted({item.provider.name for item in asset.sources if item.provider})),
            creators=tuple(sorted({item.creator_name for item in asset.sources if item.creator_name})),
            tags=tuple(sorted(tag.name for tag in asset.tags)),
            usage_count=asset.usage_count,
            recent_usage_count=recent_count,
            last_used_at=asset.last_used_at,
        )


def _apply_search_filters(statement, request: SearchMediaRequest):
    if request.media_type:
        statement = statement.where(MediaAsset.media_type == request.media_type)
    if request.orientation == "landscape":
        statement = statement.where(MediaAsset.width > MediaAsset.height)
    elif request.orientation == "portrait":
        statement = statement.where(MediaAsset.height > MediaAsset.width)
    elif request.orientation == "square":
        statement = statement.where(MediaAsset.width == MediaAsset.height)
    if request.mime_type:
        statement = statement.where(func.lower(MediaAsset.mime_type) == request.mime_type.casefold())
    if request.min_width is not None:
        statement = statement.where(MediaAsset.width >= request.min_width)
    if request.min_height is not None:
        statement = statement.where(MediaAsset.height >= request.min_height)
    if request.min_duration_ms is not None:
        statement = statement.where(MediaAsset.duration_ms >= request.min_duration_ms)
    if request.max_duration_ms is not None:
        statement = statement.where(MediaAsset.duration_ms <= request.max_duration_ms)
    if request.provider:
        statement = statement.where(
            MediaAsset.sources.any(
                MediaSource.provider.has(func.lower(MediaProvider.name) == request.provider.casefold())
            )
        )
    for tag in request.tags:
        statement = statement.where(MediaAsset.tags.any(func.lower(Tag.name) == tag.casefold()))
    if request.creator:
        statement = statement.where(
            MediaAsset.sources.any(MediaSource.creator_name.ilike(f"%{_escape_like(request.creator)}%", escape="\\"))
        )
    if request.usage == "unused":
        statement = statement.where(MediaAsset.usage_count == 0)
    elif request.usage == "used":
        statement = statement.where(MediaAsset.usage_count > 0)
    if request.availability == "available":
        statement = statement.where(MediaAsset.status == "active")
    elif request.availability == "missing":
        statement = statement.where(MediaAsset.status == "missing")
    if request.recently_used_within_days is not None:
        cutoff = _utcnow() - timedelta(days=request.recently_used_within_days)
        statement = statement.where(MediaAsset.usages.any(AssetUsage.used_at >= cutoff))
    if request.story_id is not None:
        statement = statement.where(MediaAsset.usages.any(AssetUsage.story_id == request.story_id))
    if request.project_id is not None:
        statement = statement.where(MediaAsset.usages.any(_usage_project_clause(request.project_id)))
    return statement


def _rank_asset(
    asset: MediaAsset,
    request: SearchMediaRequest,
    tokens: tuple[str, ...],
    recent_count: int,
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    if _asset_available(asset):
        score += 40
        reasons.append("available:+40")
    path = asset.relative_path.casefold()
    title = (asset.title or "").casefold()
    description = (asset.description or "").casefold()
    tags = {tag.name.casefold() for tag in asset.tags}
    creators = " ".join(item.creator_name or "" for item in asset.sources).casefold()
    providers = " ".join(item.provider.name if item.provider else "" for item in asset.sources).casefold()
    acquisition = _provider_search_text(asset).casefold()
    query = request.query.casefold().strip()
    if query and query in path:
        score += 25
        reasons.append("path_phrase:+25")
    if query and query == title:
        score += 30
        reasons.append("exact_title:+30")
    for token in tokens:
        if token in tags:
            score += 30
            reasons.append(f"exact_tag:{token}:+30")
        elif any(token in tag for tag in tags):
            score += 20
            reasons.append(f"tag:{token}:+20")
        if token in title:
            score += 15
            reasons.append(f"title:{token}:+15")
        if token in path:
            score += 12
            reasons.append(f"path:{token}:+12")
        if token in creators or token in providers:
            score += 8
            reasons.append(f"provenance:{token}:+8")
        if token in description:
            score += 4
            reasons.append(f"description:{token}:+4")
        if token in acquisition:
            score += 12
            reasons.append(f"provider_search_provenance:{token}:+12")
    if request.media_type:
        score += 5
        reasons.append("media_type_match:+5")
    if request.orientation:
        score += 5
        reasons.append("orientation_match:+5")
    usage_bonus = max(0, 20 - min(20, asset.usage_count * 2))
    score += usage_bonus
    reasons.append(f"low_total_usage:+{usage_bonus}")
    recent_bonus = max(0, 15 - min(15, recent_count * 5))
    score += recent_bonus
    reasons.append(f"low_recent_usage:+{recent_bonus}")
    return score, reasons


def _matches_all_tokens(asset: MediaAsset, tokens: tuple[str, ...]) -> bool:
    text = " ".join(
        [
            asset.relative_path,
            asset.title or "",
            asset.description or "",
            asset.mime_type or "",
            _provider_search_text(asset),
            *(tag.name for tag in asset.tags),
            *(source.creator_name or "" for source in asset.sources),
            *(source.provider.name if source.provider else "" for source in asset.sources),
            *(usage.segment_label or "" for usage in asset.usages),
            *(usage.usage_reference or "" for usage in asset.usages),
            *(usage.story.title if usage.story else "" for usage in asset.usages),
            *(
                (usage.project or (usage.story.project if usage.story else None)).title
                if (usage.project or (usage.story.project if usage.story else None))
                else ""
                for usage in asset.usages
            ),
        ]
    ).casefold()
    return all(token in text for token in tokens)


def _provider_search_text(asset: MediaAsset) -> str:
    """Return only the namespaced, deterministic acquisition search terms."""
    metadata = asset.technical_metadata
    if not isinstance(metadata, dict):
        return ""
    acquisition = metadata.get("provider_acquisition")
    if not isinstance(acquisition, dict):
        return ""
    searches = acquisition.get("searches")
    if not isinstance(searches, list):
        return ""
    values: list[str] = []
    for search in searches:
        if not isinstance(search, dict):
            continue
        query = search.get("query")
        if isinstance(query, str):
            values.append(query)
        required_terms = search.get("required_terms")
        if isinstance(required_terms, list):
            values.extend(item for item in required_terms if isinstance(item, str))
    return " ".join(values)


def _usage_project_clause(project_id: int):
    return or_(
        AssetUsage.project_id == project_id,
        AssetUsage.story.has(Story.project_id == project_id),
    )


def _asset_summary_loaders():
    return (
        selectinload(MediaAsset.locations),
        selectinload(MediaAsset.sources).selectinload(MediaSource.provider),
        selectinload(MediaAsset.tags),
        selectinload(MediaAsset.usages).selectinload(AssetUsage.project),
        selectinload(MediaAsset.usages).selectinload(AssetUsage.story).selectinload(Story.project),
    )


def _asset_detail_loaders():
    return (*_asset_summary_loaders(), selectinload(MediaAsset.license))


def _usage_loaders():
    return (
        selectinload(AssetUsage.asset),
        selectinload(AssetUsage.project),
        selectinload(AssetUsage.story).selectinload(Story.project),
    )


def _usage_result(usage: AssetUsage) -> UsageResult:
    project = usage.project or (usage.story.project if usage.story else None)
    return UsageResult(
        usage_id=usage.id,
        asset_id=usage.asset_id,
        project_id=project.id if project else None,
        project_slug=project.slug if project else None,
        project_title=project.title if project else None,
        story_id=usage.story.id if usage.story else None,
        story_position=usage.story.position if usage.story else None,
        story_title=usage.story.title if usage.story else None,
        usage_reference=usage.usage_reference,
        segment_label=usage.segment_label,
        narration_start_ms=usage.narration_start_ms,
        narration_end_ms=usage.narration_end_ms,
        usage_role=usage.usage_role,
        used_at=usage.used_at,
        notes=usage.notes,
        idempotency_key=usage.idempotency_key,
    )


def _location_result(location: MediaLocation) -> MediaLocationResult:
    return MediaLocationResult(
        relative_path=location.relative_path,
        status=location.status,
        provenance_type=location.provenance_type,
        file_size_bytes=location.file_size_bytes,
        file_modified_at=location.file_modified_at,
        first_seen_at=location.first_seen_at,
        last_seen_at=location.last_seen_at,
        missing_since=location.missing_since,
    )


def _source_result(source: MediaSource) -> MediaSourceResult:
    return MediaSourceResult(
        provider=source.provider.name if source.provider else None,
        provider_website_url=source.provider.website_url if source.provider else None,
        provider_asset_id=source.provider_asset_id,
        source_url=source.source_url,
        creator_name=source.creator_name,
        creator_url=source.creator_url,
        original_filename=source.original_filename,
        acquired_at=source.acquired_at,
    )


def _license_result(license_record) -> LicenseResult:
    return LicenseResult(
        license_name=license_record.license_name,
        license_url=license_record.license_url,
        attribution_required=license_record.attribution_required,
        attribution_text=license_record.attribution_text,
        usage_terms=license_record.usage_terms,
        commercial_use_allowed=license_record.commercial_use_allowed,
        modifications_allowed=license_record.modifications_allowed,
        verified_at=license_record.verified_at,
    )


def _current_location(asset: MediaAsset) -> str | None:
    available = sorted(
        (item.relative_path for item in asset.locations if item.status == "available"),
        key=str.casefold,
    )
    if not available:
        return asset.relative_path if not asset.locations and asset.status == "active" else None
    for path in available:
        if path.casefold() == asset.relative_path.casefold():
            return path
    return available[0]


def _asset_available(asset: MediaAsset) -> bool:
    return any(item.status == "available" for item in asset.locations) or (
        not asset.locations and asset.status == "active"
    )


def _orientation(width: int | None, height: int | None) -> str | None:
    if width is None or height is None:
        return None
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _same_datetime(left: datetime, right: datetime) -> bool:
    return _as_utc(left) == _as_utc(right)


def _datetime_sort(value: datetime | None) -> float:
    return _as_utc(value).timestamp() if value else 0.0


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
