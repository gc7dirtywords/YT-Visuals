from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import Engine, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..models import AssetUsage, MediaAsset, MediaLocation, MediaProvider, MediaSource, Project, Story, Tag


@dataclass(frozen=True, slots=True)
class LibrarySearchFilters:
    media_type: str | None = None
    orientation: str | None = None
    usage: str | None = None
    missing: bool = False
    provider: str | None = None
    mime_type: str | None = None
    min_width: int | None = None
    min_height: int | None = None
    min_duration_ms: int | None = None
    max_duration_ms: int | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class LibrarySearchResult:
    id: int
    relative_path: str
    locations: tuple[str, ...]
    media_type: str
    mime_type: str | None
    width: int | None
    height: int | None
    duration_ms: int | None
    orientation: str | None
    status: str
    sha256: str | None
    usage_count: int
    last_used_at: str | None
    providers: tuple[str, ...]
    creators: tuple[str, ...]
    tags: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LibraryStatus:
    total_assets: int
    active_assets: int
    missing_assets: int
    images: int
    videos: int
    available_locations: int
    missing_locations: int
    duplicate_locations: int
    unused_assets: int
    total_bytes: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def get_library_status(engine: Engine) -> LibraryStatus:
    with Session(engine) as session:
        total_assets = session.scalar(select(func.count()).select_from(MediaAsset)) or 0
        active_assets = session.scalar(
            select(func.count()).select_from(MediaAsset).where(MediaAsset.status == "active")
        ) or 0
        locations_by_asset = session.execute(
            select(MediaLocation.media_asset_id, func.count(MediaLocation.id))
            .where(MediaLocation.status == "available")
            .group_by(MediaLocation.media_asset_id)
        ).all()
        return LibraryStatus(
            total_assets=total_assets,
            active_assets=active_assets,
            missing_assets=session.scalar(
                select(func.count()).select_from(MediaAsset).where(MediaAsset.status == "missing")
            ) or 0,
            images=session.scalar(
                select(func.count()).select_from(MediaAsset).where(MediaAsset.media_type == "image")
            ) or 0,
            videos=session.scalar(
                select(func.count()).select_from(MediaAsset).where(MediaAsset.media_type == "video")
            ) or 0,
            available_locations=sum(count for _, count in locations_by_asset),
            missing_locations=session.scalar(
                select(func.count()).select_from(MediaLocation).where(MediaLocation.status == "missing")
            ) or 0,
            duplicate_locations=sum(max(0, count - 1) for _, count in locations_by_asset),
            unused_assets=session.scalar(
                select(func.count()).select_from(MediaAsset).where(MediaAsset.usage_count == 0)
            ) or 0,
            total_bytes=session.scalar(
                select(func.coalesce(func.sum(MediaLocation.file_size_bytes), 0)).where(
                    MediaLocation.status == "available"
                )
            ) or 0,
        )


def search_library(
    engine: Engine,
    query: str = "",
    filters: LibrarySearchFilters | None = None,
) -> list[LibrarySearchResult]:
    filters = filters or LibrarySearchFilters()
    statement = select(MediaAsset).options(
        selectinload(MediaAsset.locations),
        selectinload(MediaAsset.sources).selectinload(MediaSource.provider),
        selectinload(MediaAsset.tags),
    )
    if filters.media_type:
        statement = statement.where(MediaAsset.media_type == filters.media_type)
    if filters.orientation == "landscape":
        statement = statement.where(MediaAsset.width > MediaAsset.height)
    elif filters.orientation == "portrait":
        statement = statement.where(MediaAsset.height > MediaAsset.width)
    elif filters.orientation == "square":
        statement = statement.where(MediaAsset.width == MediaAsset.height)
    if filters.usage == "unused":
        statement = statement.where(MediaAsset.usage_count == 0)
    elif filters.usage == "used":
        statement = statement.where(MediaAsset.usage_count > 0)
    if filters.missing:
        statement = statement.where(MediaAsset.status == "missing")
    else:
        statement = statement.where(MediaAsset.status == "active")
    if filters.provider:
        statement = statement.where(
            MediaAsset.sources.any(
                MediaSource.provider.has(func.lower(MediaProvider.name) == filters.provider.lower())
            )
        )
    if filters.mime_type:
        statement = statement.where(func.lower(MediaAsset.mime_type) == filters.mime_type.lower())
    if filters.min_width is not None:
        statement = statement.where(MediaAsset.width >= filters.min_width)
    if filters.min_height is not None:
        statement = statement.where(MediaAsset.height >= filters.min_height)
    if filters.min_duration_ms is not None:
        statement = statement.where(MediaAsset.duration_ms >= filters.min_duration_ms)
    if filters.max_duration_ms is not None:
        statement = statement.where(MediaAsset.duration_ms <= filters.max_duration_ms)
    if query.strip():
        pattern = f"%{_escape_like(query.strip())}%"
        statement = statement.where(
            or_(
                MediaAsset.relative_path.ilike(pattern, escape="\\"),
                MediaAsset.title.ilike(pattern, escape="\\"),
                MediaAsset.description.ilike(pattern, escape="\\"),
                MediaAsset.mime_type.ilike(pattern, escape="\\"),
                MediaAsset.locations.any(MediaLocation.relative_path.ilike(pattern, escape="\\")),
                MediaAsset.tags.any(Tag.name.ilike(pattern, escape="\\")),
                MediaAsset.sources.any(MediaSource.creator_name.ilike(pattern, escape="\\")),
                MediaAsset.sources.any(
                    MediaSource.provider.has(MediaProvider.name.ilike(pattern, escape="\\"))
                ),
                MediaAsset.usages.any(
                    or_(
                        AssetUsage.segment_label.ilike(pattern, escape="\\"),
                        AssetUsage.story.has(Story.title.ilike(pattern, escape="\\")),
                        AssetUsage.story.has(
                            Story.project.has(
                                or_(
                                    Project.title.ilike(pattern, escape="\\"),
                                    Project.slug.ilike(pattern, escape="\\"),
                                )
                            )
                        ),
                    )
                ),
            )
        )
    statement = statement.order_by(MediaAsset.relative_path).limit(filters.limit)

    with Session(engine) as session:
        assets = list(session.scalars(statement))
        return [_to_result(asset) for asset in assets]


def _to_result(asset: MediaAsset) -> LibrarySearchResult:
    providers = sorted({source.provider.name for source in asset.sources if source.provider})
    creators = sorted({source.creator_name for source in asset.sources if source.creator_name})
    return LibrarySearchResult(
        id=asset.id,
        relative_path=asset.relative_path,
        locations=tuple(sorted(item.relative_path for item in asset.locations)),
        media_type=asset.media_type,
        mime_type=asset.mime_type,
        width=asset.width,
        height=asset.height,
        duration_ms=asset.duration_ms,
        orientation=_orientation(asset.width, asset.height),
        status=asset.status,
        sha256=asset.sha256,
        usage_count=asset.usage_count,
        last_used_at=asset.last_used_at.isoformat() if asset.last_used_at else None,
        providers=tuple(providers),
        creators=tuple(creators),
        tags=tuple(sorted(tag.name for tag in asset.tags)),
    )


def _orientation(width: int | None, height: int | None) -> str | None:
    if width is None or height is None:
        return None
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
