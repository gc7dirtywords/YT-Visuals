from __future__ import annotations

import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from yt_visuals.acquisition import AcquisitionService
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.models import BeatSelection, CandidatePackage, MediaAsset, MediaDownload, MediaSource
from yt_visuals.providers.base import MediaSearchResult, ProviderInfo, SearchPage
from yt_visuals.providers.errors import MissingProviderCredentialError
from yt_visuals.workflow.artifacts import file_sha256
from yt_visuals.workflow.service import VisualWorkflowService
from yt_visuals.workflow.provider_fallback import _search


def _request(story_id: str) -> dict:
    return {
        "document_type": "visual_request", "contract_version": 1,
        "story": {
            "story_id": story_id, "title": "A Quiet Fire",
            "presentation_profile": "calm_late_night_second_monitor_v1",
        },
        "beats": [{
            "beat_id": "beat-fire", "sequence": 1, "timing": None,
            "narration_context": "A low fire glowed in the dark room.",
            "desired_visual": {"summary": "A dark fireplace", "mood": "calm"},
            "media_preference": "image", "search_concepts": ["dark fireplace"],
            "search_directives": [{
                "query": "dark fireplace", "media_type": "image",
                "required_terms": [], "excluded_terms": [],
                "filters": {"orientation": "landscape"},
            }],
            "must_have": [], "preferred": [], "avoid": [],
            "technical_constraints": {"orientation": "landscape"},
        }],
    }


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def _jpeg() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (800, 450), "#20150d").save(stream, format="JPEG")
    return stream.getvalue()


def _result() -> MediaSearchResult:
    return MediaSearchResult(
        provider="pexels", provider_asset_id="7001", media_type="image",
        title="Dark fireplace in a quiet room", description=None,
        creator_name="Example Creator", creator_url="https://www.pexels.com/@example",
        source_url="https://www.pexels.com/photo/dark-fireplace-7001/",
        download_url="https://images.pexels.com/photos/7001/fireplace.jpeg",
        preview_url=None, width=800, height=450, duration_ms=None,
        mime_type="image/jpeg", license_name="Pexels License",
        license_url="https://www.pexels.com/legal-pages/license/",
        attribution_required=False, attribution_text="Photo by Example Creator on Pexels",
        raw_metadata={"id": 7001, "alt": "Dark fireplace in a quiet room"},
        commercial_use_allowed=True, modifications_allowed=True,
        license_notes="Pexels policy mapping; third-party rights are not cleared.",
    )


class FakePexels:
    info = ProviderInfo(
        "pexels", "Pexels", "https://www.pexels.com/", "https://www.pexels.com/api/",
        "Pexels License", "https://www.pexels.com/legal-pages/license/", False,
    )

    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls

    def search_photos(self, query: str, **kwargs) -> SearchPage:  # type: ignore[no-untyped-def]
        self.calls.append({"kind": "photos", "query": query, **kwargs})
        return SearchPage((_result(),), 1, 20, 1)

    def search_videos(self, query: str, **kwargs) -> SearchPage:  # type: ignore[no-untyped-def]
        self.calls.append({"kind": "videos", "query": query, **kwargs})
        return SearchPage((), 1, 20, 0)

    def close(self) -> None:
        return None


def _complete_blocked(template: Path, destination: Path) -> Path:
    value = json.loads(template.read_text(encoding="utf-8"))
    entry = value["review_entries"][0]
    entry["editorial_guidance"] = {
        "action": "revise_search",
        "replacement_guidance": {
            "summary": "Use the explicit stock fallback.", "must_have": [],
            "preferred": [], "avoid": [],
            "revised_search_directives": [{
                "query": "dark fireplace", "media_type": "image",
                "required_terms": [], "excluded_terms": [],
                "filters": {"orientation": "landscape"},
            }],
            "media_preference_change": None, "external_sourcing_allowed": True,
        },
    }
    return _write(destination, value)


def _complete_accept(template: Path, destination: Path) -> Path:
    value = json.loads(template.read_text(encoding="utf-8"))
    value["review_entries"][0]["editorial_review"] = {
        "alignment_score": 95, "decision": "accept", "mismatch_reasons": [],
        "mismatch_explanation": None, "replacement_guidance": None,
        "catalog_annotations": None,
    }
    return _write(destination, value)


def test_phase5a_local_first_external_acquire_review_and_future_local_reuse(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    provider_calls: list[dict] = []
    provider_constructions = 0
    downloads = 0

    def provider_factory(name: str, settings: Settings) -> FakePexels:
        nonlocal provider_constructions
        assert name == "pexels"
        provider_constructions += 1
        return FakePexels(provider_calls)

    def download_handler(request: httpx.Request) -> httpx.Response:
        nonlocal downloads
        downloads += 1
        return httpx.Response(
            200,
            headers={"Content-Type": "image/jpeg", "Content-Length": str(len(_jpeg()))},
            content=_jpeg(),
        )

    client = httpx.Client(transport=httpx.MockTransport(download_handler))

    def acquisition_factory(settings: Settings, supplied_engine):  # type: ignore[no-untyped-def]
        return AcquisitionService(settings, supplied_engine, http_client=client)

    service = VisualWorkflowService(
        catalog_settings, engine,
        provider_factory=provider_factory, acquisition_factory=acquisition_factory,
    )
    first = service.start_workflow(
        _write(catalog_settings.root / "request-one.json", _request("story-fire-one"))
    )
    package_one = service.generate_package(first.workflow_id)
    first_report = json.loads(
        (catalog_settings.root / package_one.candidate_report_path).read_text(encoding="utf-8")
    )
    assert first_report["contract_version"] == 2
    assert first_report["beats"][0]["blocked_reason"]["code"] == "no_local_matches"
    assert provider_constructions == 0 and provider_calls == [] and downloads == 0

    service.import_review(
        first.workflow_id,
        _complete_blocked(
            catalog_settings.root / package_one.review_template_path,
            catalog_settings.root / "allow-external.json",
        ),
    )
    package_two = service.generate_package(first.workflow_id)
    report_path = catalog_settings.root / package_two.candidate_report_path
    template_path = catalog_settings.root / package_two.review_template_path
    storyboard_path = catalog_settings.root / package_two.storyboard_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))
    candidate = report["beats"][0]["candidates"][0]
    assert package_two.iteration == 2
    assert candidate["catalog_status"] == "newly_downloaded"
    assert candidate["provenance"]["provider"] == "pexels"
    assert candidate["license"]["status"] == "known"
    assert provider_calls == [{
        "kind": "photos", "query": "dark fireplace", "orientation": "landscape",
        "page": 1, "per_page": 20,
    }]
    assert downloads == 1
    assert storyboard_path.stat().st_size > 0
    assert template["contract_version"] == 2
    assert template["bookkeeping"]["candidate_report_sha256"] == file_sha256(report_path)
    assert template["bookkeeping"]["storyboard_pdf_sha256"] == file_sha256(storyboard_path)

    imported_review = service.import_review(
        first.workflow_id,
        _complete_accept(template_path, catalog_settings.root / "accepted.json"),
    )
    assert imported_review.workflow_status == "complete"
    with Session(engine) as session:
        selection = session.scalar(select(BeatSelection))
        asset = session.get(MediaAsset, candidate["asset_id"])
        source = session.scalar(select(MediaSource))
        history = session.scalar(select(MediaDownload))
        assert selection is not None and selection.asset_sha256 == candidate["asset_sha256"]
        assert asset is not None and asset.technical_metadata["provider_acquisition"]["searches"][0]["query"] == "dark fireplace"
        assert source is not None and source.provider_asset_id == "photo:7001"
        assert history is not None and history.status == "success"

    second = service.start_workflow(
        _write(catalog_settings.root / "request-two.json", _request("story-fire-two"))
    )
    package_three = service.generate_package(second.workflow_id)
    second_report = json.loads(
        (catalog_settings.root / package_three.candidate_report_path).read_text(encoding="utf-8")
    )
    reused = second_report["beats"][0]["candidates"][0]
    assert reused["asset_id"] == candidate["asset_id"]
    assert reused["catalog_status"] == "previously_downloaded"
    assert provider_constructions == 1 and downloads == 1
    client.close()
    engine.dispose()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("empty", "no_external_provider_matches"),
        ("excluded", "all_external_provider_matches_excluded"),
        ("technical", "no_external_provider_technically_eligible_matches"),
    ],
)
def test_external_misses_are_reviewable_v2_outcomes(
    catalog_settings: Settings, mode: str, expected: str
) -> None:
    engine = initialize_database(catalog_settings)

    class MissProvider(FakePexels):
        def search_photos(self, query: str, **kwargs) -> SearchPage:  # type: ignore[no-untyped-def]
            self.calls.append({"query": query, **kwargs})
            return SearchPage(() if mode == "empty" else (_result(),), 1, 20, 0 if mode == "empty" else 1)

    calls: list[dict] = []
    class NoDownloadAcquisition:
        def recover_incomplete(self) -> int:
            return 0
        def close(self) -> None:
            return None
        def lookup_existing(self, *args):  # type: ignore[no-untyped-def]
            raise AssertionError("ineligible results must not reach acquisition lookup")
        def acquire(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("ineligible results must not download")

    service = VisualWorkflowService(
        catalog_settings, engine,
        provider_factory=lambda name, settings: MissProvider(calls),
        acquisition_factory=lambda settings, supplied_engine: NoDownloadAcquisition(),
    )
    document = _request(f"story-{mode}")
    first = service.start_workflow(_write(catalog_settings.root / "request.json", document))
    blocked = service.generate_package(first.workflow_id)
    guidance = json.loads(
        (catalog_settings.root / blocked.review_template_path).read_text(encoding="utf-8")
    )
    directive = {
        "query": "dark fireplace", "media_type": "image", "required_terms": [],
        "excluded_terms": ["fireplace"] if mode == "excluded" else [],
        "filters": {
            "orientation": "landscape",
            **({"minimum_width": 1200} if mode == "technical" else {}),
        },
    }
    guidance["review_entries"][0]["editorial_guidance"] = {
        "action": "revise_search",
        "replacement_guidance": {
            "summary": "Use explicit fallback.", "must_have": [], "preferred": [], "avoid": [],
            "revised_search_directives": [directive], "media_preference_change": None,
            "external_sourcing_allowed": True,
        },
    }
    service.import_review(
        first.workflow_id, _write(catalog_settings.root / "guidance.json", guidance)
    )
    package = service.generate_package(first.workflow_id)
    report = json.loads(
        (catalog_settings.root / package.candidate_report_path).read_text(encoding="utf-8")
    )
    template = json.loads(
        (catalog_settings.root / package.review_template_path).read_text(encoding="utf-8")
    )
    assert report["contract_version"] == 2
    assert report["beats"][0]["blocked_reason"]["code"] == expected
    assert template["review_entries"][0]["blocked_reason"]["code"] == expected
    engine.dispose()


def test_provider_configuration_failure_is_operational_and_marks_generation_failed(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(
        catalog_settings, engine,
        provider_factory=lambda name, settings: (_ for _ in ()).throw(
            MissingProviderCredentialError("PEXELS_API_KEY is not set")
        ),
    )
    imported = service.start_workflow(
        _write(catalog_settings.root / "request.json", _request("story-provider-failure"))
    )
    first = service.generate_package(imported.workflow_id)
    service.import_review(
        imported.workflow_id,
        _complete_blocked(
            catalog_settings.root / first.review_template_path,
            catalog_settings.root / "guidance.json",
        ),
    )
    with pytest.raises(MissingProviderCredentialError, match="PEXELS_API_KEY"):
        service.generate_package(imported.workflow_id)
    with Session(engine) as session:
        package = session.scalar(
            select(CandidatePackage).order_by(CandidatePackage.iteration.desc())
        )
        assert package is not None and package.status == "generation_failed"
        assert package.review_template_path is None
    engine.dispose()


def test_either_results_merge_by_provider_position_with_image_tie_break() -> None:
    calls: list[dict] = []
    provider = FakePexels(calls)
    photos = (_result(), MediaSearchResult(**{**_result().to_dict(), "provider_asset_id": "7003"}))
    video = MediaSearchResult(**{
        **_result().to_dict(), "provider_asset_id": "7002", "media_type": "video",
        "title": None, "download_url": "https://videos.pexels.com/video/7002.mp4",
        "mime_type": "video/mp4", "duration_ms": 10_000,
    })
    provider.search_photos = lambda query, **kwargs: SearchPage(photos, 1, 20, 2)  # type: ignore[method-assign]
    provider.search_videos = lambda query, **kwargs: SearchPage((video,), 1, 20, 1)  # type: ignore[method-assign]
    merged = _search(provider, "quiet fire", None, "landscape")
    assert [(position, item.media_type, item.provider_asset_id) for position, item in merged] == [
        (1, "image", "7001"), (1, "video", "7002"), (2, "image", "7003"),
    ]


def test_workflow_service_keeps_orm_provider_distinct_from_provider_protocol() -> None:
    from yt_visuals import models
    from yt_visuals.providers import base
    from yt_visuals.workflow import service as workflow_service

    assert workflow_service.MediaProvider is models.MediaProvider
    assert workflow_service.ProviderClient is base.MediaProvider
