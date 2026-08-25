from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlsplit

from sqlalchemy import Engine

from ..acquisition import AcquisitionContext, AcquisitionOutcome, AcquisitionService
from ..config import Settings
from ..providers.base import MediaProvider, MediaSearchResult
from ..providers.registry import create_provider
from ..services import MediaCatalogService
from ..services.schemas import AssetDetailResult
from .contracts import SearchDirective, VisualBeat


ProviderFactory = Callable[[str, Settings], MediaProvider]
AcquisitionFactory = Callable[[Settings, Engine], AcquisitionService]


@dataclass(frozen=True, slots=True)
class ExternalCandidate:
    outcome: AcquisitionOutcome
    detail: AssetDetailResult
    directive: SearchDirective
    directive_index: int
    provider_rank: int
    executable_query: str


@dataclass(frozen=True, slots=True)
class ExternalResult:
    candidate: ExternalCandidate | None
    blocked_reason: dict[str, str] | None


class ProviderFallbackCoordinator:
    """Deterministic Pexels fallback using only structured executable fields."""

    def __init__(
        self,
        settings: Settings,
        engine: Engine,
        *,
        provider_factory: ProviderFactory = create_provider,
        acquisition_factory: AcquisitionFactory = AcquisitionService,
    ) -> None:
        self.settings = settings
        self.engine = engine
        self.provider_factory = provider_factory
        self.acquisition_factory = acquisition_factory
        self.catalog = MediaCatalogService(engine)

    def source(
        self,
        *,
        workflow_id: str,
        package_id: str,
        beat_row_id: str,
        beat: VisualBeat,
        rejected_ids: set[int],
        rejected_hashes: set[str],
        rejected_provider_ids: set[str],
        reserved_ids: set[int],
        reserved_hashes: set[str],
    ) -> ExternalResult:
        provider = self.provider_factory("pexels", self.settings)
        try:
            acquisition = self.acquisition_factory(self.settings, self.engine)
            saw_results = saw_excluded = saw_technical = False
            try:
                recover = getattr(acquisition, "recover_incomplete", None)
                if callable(recover):
                    recover()
                for directive_index, directive in enumerate(beat.search_directives):
                    result = self._source_directive(
                        provider, acquisition, workflow_id, package_id, beat_row_id, beat,
                        directive, directive_index, rejected_ids, rejected_hashes,
                        rejected_provider_ids, reserved_ids, reserved_hashes,
                    )
                    if isinstance(result, ExternalResult):
                        return result
                    if isinstance(result, ExternalCandidate):
                        return ExternalResult(result, None)
                    results_seen, excluded_seen, technical_seen = result
                    saw_results |= results_seen
                    saw_excluded |= excluded_seen
                    saw_technical |= technical_seen
            finally:
                acquisition.close()
        finally:
            provider.close()
        if not saw_results:
            if saw_technical:
                return _blocked("no_external_provider_technically_eligible_matches")
            return _blocked("no_external_provider_matches")
        if saw_technical:
            return _blocked("no_external_provider_technically_eligible_matches")
        if saw_excluded:
            return _blocked("all_external_provider_matches_excluded")
        return _blocked("no_external_provider_matches")

    def _source_directive(
        self,
        provider: MediaProvider,
        acquisition: AcquisitionService,
        workflow_id: str,
        package_id: str,
        beat_row_id: str,
        beat: VisualBeat,
        directive: SearchDirective,
        directive_index: int,
        rejected_ids: set[int],
        rejected_hashes: set[str],
        rejected_provider_ids: set[str],
        reserved_ids: set[int],
        reserved_hashes: set[str],
    ) -> ExternalCandidate | ExternalResult | tuple[bool, bool, bool]:
        media_type = _effective_media_type(beat.media_preference, directive.media_type)
        if media_type is False:
            return False, False, False
        constraints = _combined_filters(beat, directive)
        if constraints is None:
            return False, False, True
        query = canonical_provider_query(directive)
        ranked = _search(provider, query, media_type, constraints["orientation"])
        saw_results = saw_excluded = saw_technical = False
        for provider_rank, result in ranked:
            saw_results = True
            if result.catalog_source_id in rejected_provider_ids:
                saw_excluded = True
                continue
            if _contains_excluded_result(result, directive.excluded_terms):
                saw_excluded = True
                continue
            if not _remote_license_eligible(result) or not _technically_eligible(
                result, media_type, constraints
            ):
                saw_technical = True
                continue
            existing = acquisition.lookup_existing(
                result.provider, result.media_type, result.provider_asset_id
            )
            if existing is not None:
                detail = self.catalog.get_asset_detail(existing.asset_id)
                if not detail.available:
                    existing = None
                elif _identity_excluded(
                    detail, beat, rejected_ids, rejected_hashes,
                    reserved_ids, reserved_hashes,
                ):
                    saw_excluded = True
                    continue
                elif not _catalog_policy_eligible(detail, beat):
                    saw_technical = True
                    continue
            context = AcquisitionContext(
                workflow_id=workflow_id,
                package_id=package_id,
                beat_id=beat_row_id,
                directive_index=directive_index,
                provider_rank=provider_rank,
                executable_query=query,
                required_terms=directive.required_terms,
                directive_media_type=media_type or "either",
            )
            outcome = existing or acquisition.acquire(result, context=context)
            detail = self.catalog.get_asset_detail(outcome.asset_id)
            if not _observed_eligible(
                detail, media_type, constraints
            ) or not _catalog_policy_eligible(detail, beat):
                return _blocked("no_external_provider_technically_eligible_matches")
            if _identity_excluded(
                detail, beat, rejected_ids, rejected_hashes,
                reserved_ids, reserved_hashes,
            ):
                return _blocked("all_external_provider_matches_excluded")
            return ExternalCandidate(
                outcome, detail, directive, directive_index, provider_rank, query
            )
        return saw_results, saw_excluded, saw_technical


def canonical_provider_query(directive: SearchDirective) -> str:
    return " ".join(" ".join((directive.query, *directive.required_terms)).split())


def _search(
    provider: MediaProvider, query: str, media_type: str | None, orientation: str | None
) -> list[tuple[int, MediaSearchResult]]:
    if media_type == "image":
        return list(enumerate(provider.search_photos(
            query, orientation=orientation, page=1, per_page=20
        ).results, start=1))
    if media_type == "video":
        return list(enumerate(provider.search_videos(
            query, orientation=orientation, page=1, per_page=20
        ).results, start=1))
    photos = list(enumerate(provider.search_photos(
        query, orientation=orientation, page=1, per_page=20
    ).results, start=1))
    videos = list(enumerate(provider.search_videos(
        query, orientation=orientation, page=1, per_page=20
    ).results, start=1))
    return sorted(
        (*photos, *videos),
        key=lambda item: (
            item[0], 0 if item[1].media_type == "image" else 1,
            _provider_id_key(item[1].provider_asset_id),
        ),
    )


def _provider_id_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value.casefold())


def _contains_excluded_result(result: MediaSearchResult, terms: tuple[str, ...]) -> bool:
    if not terms:
        return False
    slug = unquote(Path(urlsplit(result.source_url).path).stem)
    content = " ".join(filter(None, (result.title, result.description, slug))).casefold()
    return any(term.casefold() in content for term in terms)


def _remote_license_eligible(result: MediaSearchResult) -> bool:
    return not (
        result.commercial_use_allowed is False or result.modifications_allowed is False
    )


def _technically_eligible(
    result: MediaSearchResult, media_type: str | None, constraints: dict[str, int | str | None]
) -> bool:
    if media_type is not None and result.media_type != media_type:
        return False
    if result.width is not None and constraints["minimum_width"] is not None:
        if result.width < int(constraints["minimum_width"]):
            return False
    if result.height is not None and constraints["minimum_height"] is not None:
        if result.height < int(constraints["minimum_height"]):
            return False
    if result.width is not None and result.height is not None:
        if not _orientation_eligible(
            result.width, result.height,
            constraints["orientation"] if isinstance(constraints["orientation"], str) else None,
        ):
            return False
    if result.media_type == "video" and result.duration_ms is not None:
        minimum = constraints["minimum_duration_ms"]
        maximum = constraints["maximum_duration_ms"]
        if minimum is not None and result.duration_ms < int(minimum):
            return False
        if maximum is not None and result.duration_ms > int(maximum):
            return False
    return True


def _observed_eligible(
    detail: AssetDetailResult, media_type: str | None, constraints: dict[str, int | str | None]
) -> bool:
    if detail.width is None or detail.height is None:
        return False
    if media_type is not None and detail.media_type != media_type:
        return False
    minimum_width, minimum_height = constraints["minimum_width"], constraints["minimum_height"]
    if minimum_width is not None and detail.width < int(minimum_width):
        return False
    if minimum_height is not None and detail.height < int(minimum_height):
        return False
    if not _orientation_eligible(
        detail.width, detail.height,
        constraints["orientation"] if isinstance(constraints["orientation"], str) else None,
    ):
        return False
    if detail.media_type == "video":
        if detail.duration_ms is None:
            return False
        minimum, maximum = constraints["minimum_duration_ms"], constraints["maximum_duration_ms"]
        if minimum is not None and detail.duration_ms < int(minimum):
            return False
        if maximum is not None and detail.duration_ms > int(maximum):
            return False
    return True


def _orientation_eligible(
    width: int, height: int, orientation: str | None
) -> bool:
    if orientation is None:
        return True
    if orientation == "landscape":
        return width > height
    if orientation == "portrait":
        return height > width
    return width == height


def _identity_excluded(
    detail: AssetDetailResult, beat: VisualBeat, rejected_ids: set[int], rejected_hashes: set[str],
    reserved_ids: set[int], reserved_hashes: set[str],
) -> bool:
    if detail.asset_id in rejected_ids or detail.sha256 in rejected_hashes:
        return True
    return not beat.repeat_within_story and (
        detail.asset_id in reserved_ids or detail.sha256 in reserved_hashes
    )


def _catalog_policy_eligible(detail: AssetDetailResult, beat: VisualBeat) -> bool:
    if beat.prior_usage_policy == "forbid_prior_usage" and detail.usage_count > 0:
        return False
    license_record = detail.license
    return license_record is None or not (
        license_record.commercial_use_allowed is False
        or license_record.modifications_allowed is False
    )


def _blocked(code: str) -> ExternalResult:
    explanations = {
        "no_external_provider_matches": "Pexels returned no results for the explicit executable directives.",
        "all_external_provider_matches_excluded": "Pexels results were excluded by explicit terms, rejection history, or reservations.",
        "no_external_provider_technically_eligible_matches": "Pexels results did not meet the structured technical or licensing requirements.",
    }
    return ExternalResult(None, {"code": code, "explanation": explanations[code]})


# Kept local to avoid coupling this orchestration boundary to service internals.
def _effective_media_type(preference: str, directive_type: str) -> str | None | bool:
    if preference == "either" and directive_type == "either":
        return None
    if preference == "either":
        return directive_type
    if directive_type == "either":
        return preference
    return preference if preference == directive_type else False


def _combined_filters(beat: VisualBeat, directive: SearchDirective) -> dict[str, int | str | None] | None:
    technical, supplied = beat.technical_constraints, directive.filters
    orientation = supplied.orientation
    if technical.orientation != "any":
        if orientation and orientation != technical.orientation:
            return None
        orientation = technical.orientation
    duration = technical.video_duration_ms
    mins = [v for v in (supplied.minimum_duration_ms, duration.minimum if duration else None) if v is not None]
    maxs = [v for v in (supplied.maximum_duration_ms, duration.maximum if duration else None) if v is not None]
    minimum_duration, maximum_duration = (max(mins) if mins else None), (min(maxs) if maxs else None)
    if minimum_duration is not None and maximum_duration is not None and maximum_duration < minimum_duration:
        return None
    return {
        "orientation": orientation,
        "minimum_width": max(
            (v for v in (supplied.minimum_width, technical.minimum_width) if v is not None),
            default=None,
        ),
        "minimum_height": max(
            (v for v in (supplied.minimum_height, technical.minimum_height) if v is not None),
            default=None,
        ),
        "minimum_duration_ms": minimum_duration,
        "maximum_duration_ms": maximum_duration,
    }
