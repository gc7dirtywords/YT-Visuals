from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from yt_visuals.config import Settings
from yt_visuals.cli import cli
from yt_visuals.database import initialize_database
from yt_visuals.models import (
    AssetLicense,
    AssetUsage,
    MediaAsset,
    MediaLocation,
    MediaProvider,
    MediaSource,
    Project,
    Story,
    Tag,
)
from yt_visuals.services import (
    AssetNotFoundError,
    AssetUnavailableError,
    InvalidUsageReferenceError,
    MediaCatalogService,
    RecentUsageRequest,
    RecordUsageRequest,
    SearchMediaRequest,
)


def seed_catalog(settings: Settings):
    engine = initialize_database(settings)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        project = Project(slug="episode-7", title="Episode Seven", episode_number=7)
        story = Story(position=1, title="Factory Story")
        project.stories.append(story)

        best = MediaAsset(
            relative_path="Library/Images/abandoned-factory.jpg",
            media_type="image",
            status="active",
            title="Abandoned Factory",
            description="Industrial exterior",
            mime_type="image/jpeg",
            file_size_bytes=100,
            sha256="a" * 64,
            width=1920,
            height=1080,
            technical_metadata={"safe": "value"},
        )
        best.locations.append(
            MediaLocation(
                relative_path=best.relative_path,
                status="available",
                provenance_type="local_import",
                file_size_bytes=100,
                first_seen_at=now - timedelta(days=10),
                last_seen_at=now,
            )
        )
        best.tags.extend([Tag(name="factory"), Tag(name="industrial")])
        best.sources.append(
            MediaSource(
                provider=MediaProvider(name="pexels", website_url="https://www.pexels.com/"),
                provider_asset_id="photo:100",
                source_url="https://www.pexels.com/photo/100/",
                creator_name="Alex Creator",
                creator_url="https://www.pexels.com/@alex",
            )
        )
        best.license = AssetLicense(
            license_name="Pexels License",
            license_url="https://www.pexels.com/legal-pages/license/",
            attribution_required=False,
            attribution_text="Photo by Alex Creator on Pexels",
        )

        used = MediaAsset(
            relative_path="Library/Images/factory-used.jpg",
            media_type="image",
            status="active",
            title="Factory Used",
            mime_type="image/jpeg",
            file_size_bytes=200,
            sha256="b" * 64,
            width=1600,
            height=900,
        )
        used.locations.append(
            MediaLocation(
                relative_path=used.relative_path,
                status="available",
                provenance_type="provider_download",
                file_size_bytes=200,
                first_seen_at=now - timedelta(days=20),
                last_seen_at=now,
            )
        )
        used.tags.append(Tag(name="factory-used"))
        used.usages.extend(
            [
                AssetUsage(
                    project=project,
                    story=story,
                    usage_reference="visual-1",
                    segment_label="Opening",
                    used_at=now - timedelta(days=2),
                ),
                AssetUsage(
                    project=project,
                    story=story,
                    usage_reference="visual-2",
                    segment_label="Middle",
                    used_at=now - timedelta(days=1),
                ),
            ]
        )

        missing = MediaAsset(
            relative_path="Library/Images/missing-portrait.png",
            media_type="image",
            status="missing",
            mime_type="image/png",
            file_size_bytes=50,
            sha256="c" * 64,
            width=600,
            height=900,
        )
        missing.locations.append(
            MediaLocation(
                relative_path=missing.relative_path,
                status="missing",
                provenance_type="local_import",
                file_size_bytes=50,
                first_seen_at=now - timedelta(days=30),
                last_seen_at=now - timedelta(days=5),
                missing_since=now - timedelta(days=5),
            )
        )
        session.add_all([project, best, used, missing])
        session.commit()
        return engine, best.id, used.id, missing.id, project.id, story.id


def test_search_service_filters_and_deterministic_ranking(catalog_settings: Settings) -> None:
    engine, best_id, used_id, _, project_id, story_id = seed_catalog(catalog_settings)
    service = MediaCatalogService(engine)
    result = service.search_media(
        SearchMediaRequest(
            query="factory",
            media_type="image",
            orientation="landscape",
            provider="PEXELS",
            tags=("factory",),
            creator="Alex",
            usage="unused",
        )
    )
    assert result.returned == 1
    assert result.candidates[0].asset_id == best_id
    assert result.candidates[0].rank == 1
    assert result.candidates[0].available is True
    assert any("exact_tag" in reason for reason in result.candidates[0].score_reasons)

    ranked = service.search_media(SearchMediaRequest(query="factory"))
    assert [item.asset_id for item in ranked.candidates[:2]] == [best_id, used_id]
    assert ranked.candidates[0].score > ranked.candidates[1].score

    by_context = service.search_media(
        SearchMediaRequest(project_id=project_id, story_id=story_id, recently_used_within_days=7)
    )
    assert [item.asset_id for item in by_context.candidates] == [used_id]
    engine.dispose()


def test_asset_detail_is_complete_and_serializable(catalog_settings: Settings) -> None:
    engine, best_id, _, _, _, _ = seed_catalog(catalog_settings)
    detail = MediaCatalogService(engine).get_asset_detail(best_id)
    assert detail.asset_id == best_id
    assert detail.current_location == "Library/Images/abandoned-factory.jpg"
    assert detail.extension == ".jpg"
    assert detail.orientation == "landscape"
    assert detail.available is True
    assert detail.first_seen_at is not None
    assert detail.last_seen_at is not None
    assert detail.sources[0].provider == "pexels"
    assert detail.sources[0].creator_name == "Alex Creator"
    assert detail.license is not None
    assert detail.license.attribution_text == "Photo by Alex Creator on Pexels"
    assert detail.tags == ("factory", "industrial")
    payload = json.loads(detail.model_dump_json())
    assert payload["asset_id"] == best_id
    assert "PEXELS_API_KEY" not in detail.model_dump_json()
    assert "authorization" not in detail.model_dump_json().lower()
    engine.dispose()


def test_library_status_service(catalog_settings: Settings) -> None:
    engine, *_ = seed_catalog(catalog_settings)
    status = MediaCatalogService(engine).get_library_status(recent_window_days=7)
    assert status.total_assets == 3
    assert status.available_assets == 2
    assert status.missing_assets == 1
    assert status.images == 3
    assert status.videos == 0
    assert status.local_import_locations == 2
    assert status.provider_download_locations == 1
    assert status.unused_assets == 2
    assert status.recently_used_assets == 1
    assert status.last_scan_at is None
    assert status.last_scan_status is None
    engine.dispose()


def test_recent_usage_filters(catalog_settings: Settings) -> None:
    engine, _, used_id, _, project_id, story_id = seed_catalog(catalog_settings)
    service = MediaCatalogService(engine)
    result = service.get_recent_usage(
        RecentUsageRequest(asset_id=used_id, project_id=project_id, story_id=story_id, limit=1)
    )
    assert result.returned == 1
    assert result.usages[0].asset_id == used_id
    assert result.usages[0].project_id == project_id
    assert result.usages[0].story_id == story_id
    assert result.usages[0].usage_reference == "visual-2"
    engine.dispose()


def test_record_usage_and_idempotent_retry(catalog_settings: Settings) -> None:
    engine, best_id, _, _, project_id, story_id = seed_catalog(catalog_settings)
    service = MediaCatalogService(engine)
    request = RecordUsageRequest(
        asset_id=best_id,
        idempotency_key="episode-7-story-1-visual-3",
        project_id=project_id,
        story_id=story_id,
        usage_reference="visual-3",
        segment_label="Closing",
        narration_start_ms=10_000,
        narration_end_ms=15_000,
        usage_role="b-roll",
    )
    first = service.record_usage(request)
    second = service.record_usage(request)
    assert first.created is True
    assert second.created is False
    assert second.usage.usage_id == first.usage.usage_id
    assert second.asset_usage_count == 1

    recent = service.get_recent_usage(RecentUsageRequest(asset_id=best_id))
    assert recent.returned == 1
    with pytest.raises(InvalidUsageReferenceError):
        service.record_usage(request.model_copy(update={"segment_label": "Different"}))
    engine.dispose()


def test_project_only_and_unassigned_usage_context(catalog_settings: Settings) -> None:
    engine, best_id, _, _, project_id, _ = seed_catalog(catalog_settings)
    service = MediaCatalogService(engine)
    project_only = service.record_usage(
        RecordUsageRequest(
            asset_id=best_id,
            idempotency_key="project-only",
            project_id=project_id,
            usage_reference="thumbnail",
        )
    )
    unassigned = service.record_usage(
        RecordUsageRequest(asset_id=best_id, idempotency_key="unassigned")
    )
    assert project_only.usage.project_id == project_id
    assert project_only.usage.story_id is None
    assert unassigned.usage.project_id is None
    assert unassigned.usage.story_id is None
    engine.dispose()


def test_service_errors_for_invalid_and_missing_assets(catalog_settings: Settings) -> None:
    engine, _, _, missing_id, _, _ = seed_catalog(catalog_settings)
    service = MediaCatalogService(engine)
    with pytest.raises(AssetNotFoundError) as not_found:
        service.get_asset_detail(99999)
    assert not_found.value.code == "asset_not_found"
    with pytest.raises(AssetUnavailableError) as unavailable:
        service.record_usage(
            RecordUsageRequest(asset_id=missing_id, idempotency_key="missing-not-allowed")
        )
    assert unavailable.value.code == "asset_unavailable"
    allowed = service.record_usage(
        RecordUsageRequest(
            asset_id=missing_id,
            idempotency_key="missing-explicitly-allowed",
            allow_missing=True,
        )
    )
    assert allowed.created is True
    assert allowed.usage.asset_id == missing_id
    engine.dispose()


def test_service_models_publish_json_schema() -> None:
    schema = SearchMediaRequest.model_json_schema()
    assert schema["type"] == "object"
    assert "media_type" in schema["properties"]
    assert "orientation" in schema["properties"]


def test_cli_reports_service_validation_without_traceback(
    catalog_settings: Settings, capsys
) -> None:
    assert cli(["library", "search", "--limit", "0"], settings=catalog_settings) == 1
    output = capsys.readouterr().out
    assert "Error [invalid_filter]" in output
    assert "limit" in output
