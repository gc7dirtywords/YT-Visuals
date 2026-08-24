from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.library import LibraryScanner
from yt_visuals.models import (
    AssetLicense,
    AssetReviewAnnotation,
    BeatAssetRejection,
    BeatSelection,
    CandidatePackage,
    MediaAsset,
    VisualBeat,
)
from yt_visuals.workflow.artifacts import file_sha256
from yt_visuals.workflow.service import VisualWorkflowError, VisualWorkflowService


def visual_request(*, query: str = "night train", beat_id: str = "beat-001") -> dict:
    return {
        "document_type": "visual_request",
        "contract_version": 1,
        "story": {
            "story_id": "story-night-train",
            "title": "The Night Train",
            "presentation_profile": "calm_late_night_second_monitor_v1",
        },
        "beats": [
            {
                "beat_id": beat_id,
                "sequence": 1,
                "timing": None,
                "narration_context": "A train crossed the sleeping countryside.",
                "desired_visual": {
                    "summary": "A train in a quiet nocturnal landscape",
                    "subjects": ["train"],
                    "mood": "calm",
                },
                "media_preference": "image",
                "search_concepts": ["night train"],
                "search_directives": [
                    {
                        "query": query,
                        "media_type": "image",
                        "required_terms": [],
                        "excluded_terms": [],
                        "filters": {"orientation": "landscape"},
                    }
                ],
                "must_have": ["night"],
                "preferred": [],
                "avoid": [],
                "technical_constraints": {"orientation": "landscape"},
            }
        ],
    }


def write_document(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return path


def seed_image(settings: Settings, name: str, color: str = "navy", *, license_state: str = "unknown") -> int:
    path = settings.root / "Library" / "Images" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (640, 360), color).save(path)
    engine = initialize_database(settings)
    LibraryScanner(settings, engine).scan()
    with Session(engine) as session:
        asset = session.scalar(select(MediaAsset).where(MediaAsset.relative_path.endswith(name)))
        assert asset is not None
        if license_state != "unknown" and asset.license is None:
            allowed = license_state == "known"
            asset.license = AssetLicense(
                license_name="Test License",
                attribution_required=False,
                commercial_use_allowed=allowed,
                modifications_allowed=allowed,
            )
            session.commit()
        asset_id = asset.id
    engine.dispose()
    return asset_id


def complete_review(template_path: Path, destination: Path, *, decision: str, score: int = 95) -> Path:
    value = json.loads(template_path.read_text(encoding="utf-8"))
    for entry in value["review_entries"]:
        if entry["entry_type"] == "candidate_review":
            replacement = decision == "replace"
            entry["editorial_review"] = {
                "alignment_score": score,
                "decision": decision,
                "mismatch_reasons": (
                    [{"category": "mood", "explanation": "The image is too bright."}]
                    if replacement
                    else []
                ),
                "mismatch_explanation": None,
                "replacement_guidance": (
                    {
                        "summary": "Use another explicit local search.",
                        "must_have": ["night"],
                        "preferred": [],
                        "avoid": [],
                        "revised_search_directives": [
                            {
                                "query": "night train",
                                "media_type": "image",
                                "required_terms": [],
                                "excluded_terms": [],
                                "filters": {"orientation": "landscape"},
                            }
                        ],
                        "media_preference_change": None,
                        "external_sourcing_allowed": False,
                    }
                    if replacement
                    else None
                ),
                "catalog_annotations": (
                    {
                        "descriptive_tags": ["train", "night"],
                        "visual_concepts": ["quiet travel"],
                        "historical_era": None,
                        "setting": "countryside",
                        "moods": ["calm"],
                    }
                    if decision == "accept"
                    else None
                ),
            }
        else:
            entry["editorial_guidance"] = {
                "action": "revise_search",
                "replacement_guidance": {
                    "summary": "Try a broader explicit local query.",
                    "must_have": [],
                    "preferred": [],
                    "avoid": [],
                    "revised_search_directives": [
                        {
                            "query": "night train",
                            "media_type": "image",
                            "required_terms": [],
                            "excluded_terms": [],
                            "filters": {"orientation": "landscape"},
                        }
                    ],
                    "media_preference_change": "image",
                    "external_sourcing_allowed": False,
                },
            }
    return write_document(destination, value)


def test_end_to_end_artifact_order_review_lock_and_annotations(
    catalog_settings: Settings,
) -> None:
    asset_id = seed_image(catalog_settings, "night-train.png")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    request_path = write_document(catalog_settings.root / "request.json", visual_request())
    imported = service.start_workflow(request_path)
    package = service.generate_package(imported.workflow_id)

    report_path = catalog_settings.root / package.candidate_report_path
    storyboard_path = catalog_settings.root / package.storyboard_path
    template_path = catalog_settings.root / package.review_template_path
    report = json.loads(report_path.read_text(encoding="utf-8"))
    template = json.loads(template_path.read_text(encoding="utf-8"))

    assert report["beats"][0]["candidates"][0]["asset_id"] == asset_id
    assert len(report["beats"][0]["candidates"]) == 1
    assert "candidate_report_sha256" not in report
    assert "storyboard_pdf_sha256" not in report
    assert "review_template_sha256" not in report
    assert template["bookkeeping"]["candidate_report_sha256"] == file_sha256(report_path)
    assert template["bookkeeping"]["storyboard_pdf_sha256"] == file_sha256(storyboard_path)
    assert storyboard_path.read_bytes().count(b"LICENSE: UNKNOWN") >= 2
    assert b"retrieval_score" not in storyboard_path.read_bytes()

    completed_path = complete_review(template_path, catalog_settings.root / "completed-review.json", decision="accept")
    result = service.import_review(imported.workflow_id, completed_path)
    assert result.accepted == 1
    assert result.workflow_status == "complete"
    retry = service.import_review(imported.workflow_id, completed_path)
    assert retry.idempotent is True
    with Session(engine) as session:
        selection = session.scalar(select(BeatSelection))
        annotation = session.scalar(select(AssetReviewAnnotation))
        asset = session.get(MediaAsset, asset_id)
        assert selection is not None and selection.alignment_score == 95
        assert annotation is not None
        assert annotation.source_type == "chatgpt_visual_review"
        assert asset is not None and asset.tags == []
    engine.dispose()


def test_rejection_excludes_same_asset_and_allows_next_local_candidate(
    catalog_settings: Settings,
) -> None:
    first_id = seed_image(catalog_settings, "night-train-a.png", "navy")
    second_id = seed_image(catalog_settings, "night-train-b.png", "black")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", visual_request())
    )
    first_package = service.generate_package(imported.workflow_id)
    first_report = json.loads(
        (catalog_settings.root / first_package.candidate_report_path).read_text(encoding="utf-8")
    )
    rejected_asset = first_report["beats"][0]["candidates"][0]["asset_id"]
    assert rejected_asset in {first_id, second_id}
    completed = complete_review(
        catalog_settings.root / first_package.review_template_path,
        catalog_settings.root / "rejected.json",
        decision="replace",
        score=60,
    )
    service.import_review(imported.workflow_id, completed)
    second_package = service.generate_package(imported.workflow_id)
    second_report = json.loads(
        (catalog_settings.root / second_package.candidate_report_path).read_text(encoding="utf-8")
    )
    assert second_package.iteration == 2
    assert second_report["beats"][0]["candidates"][0]["asset_id"] != rejected_asset
    with Session(engine) as session:
        rejection = session.scalar(select(BeatAssetRejection))
        assert rejection is not None and rejection.asset_id == rejected_asset
    engine.dispose()


def test_blocked_no_candidate_gets_guidance_and_returns_to_sourcing(
    catalog_settings: Settings,
) -> None:
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", visual_request(query="missing concept"))
    )
    package = service.generate_package(imported.workflow_id)
    template_path = catalog_settings.root / package.review_template_path
    template = json.loads(template_path.read_text(encoding="utf-8"))
    assert template["review_entries"][0]["entry_type"] == "blocked_beat_guidance"
    assert "alignment_score" not in template["review_entries"][0]
    completed = complete_review(template_path, catalog_settings.root / "guidance.json", decision="replace")
    result = service.import_review(imported.workflow_id, completed)
    assert result.guidance == 1
    assert service.get_status(imported.workflow_id)["beat_states"] == {"rejected": 1}
    engine.dispose()


def test_review_rejects_modified_bookkeeping_and_artifact_hash(
    catalog_settings: Settings,
) -> None:
    seed_image(catalog_settings, "night-train.png")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", visual_request())
    )
    package = service.generate_package(imported.workflow_id)
    template_path = catalog_settings.root / package.review_template_path
    completed_path = complete_review(template_path, catalog_settings.root / "completed.json", decision="accept")
    modified = json.loads(completed_path.read_text(encoding="utf-8"))
    modified["bookkeeping"]["iteration"] = 99
    write_document(completed_path, modified)
    with pytest.raises(VisualWorkflowError, match="bookkeeping"):
        service.import_review(imported.workflow_id, completed_path)

    completed_path = complete_review(template_path, catalog_settings.root / "completed.json", decision="accept")
    report_path = catalog_settings.root / package.candidate_report_path
    report_path.write_text(report_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(VisualWorkflowError, match="Candidate Report hash"):
        service.import_review(imported.workflow_id, completed_path)
    engine.dispose()


def test_lock_compatibility_and_workflow_wide_iteration(
    catalog_settings: Settings,
) -> None:
    seed_image(catalog_settings, "night-train.png")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    request_path = write_document(catalog_settings.root / "request.json", visual_request())
    imported = service.start_workflow(request_path)
    package = service.generate_package(imported.workflow_id)
    completed = complete_review(
        catalog_settings.root / package.review_template_path,
        catalog_settings.root / "accepted.json",
        decision="accept",
    )
    service.import_review(imported.workflow_id, completed)

    timing_change = visual_request()
    timing_change["beats"][0]["timing"] = {
        "start_ms": 10_000,
        "end_ms": 20_000,
        "precision": "exact",
    }
    revised = service.revise_workflow(
        imported.workflow_id,
        write_document(catalog_settings.root / "revision.json", timing_change),
    )
    assert revised.request_revision == 2
    next_package = service.generate_package(imported.workflow_id)
    assert next_package.iteration == 2

    # Close the carry-forward package with its empty review before another revision.
    empty_review = json.loads(
        (catalog_settings.root / next_package.review_template_path).read_text(encoding="utf-8")
    )
    empty_path = write_document(catalog_settings.root / "empty-review.json", empty_review)
    service.import_review(imported.workflow_id, empty_path)

    incompatible = deepcopy(timing_change)
    incompatible["beats"][0]["desired_visual"]["summary"] = "A bright station interior"
    with pytest.raises(VisualWorkflowError, match="incompatible"):
        service.revise_workflow(
            imported.workflow_id,
            write_document(catalog_settings.root / "incompatible.json", incompatible),
        )
    engine.dispose()


def test_known_restricted_license_is_ineligible_and_only_one_package_awaits(
    catalog_settings: Settings,
) -> None:
    seed_image(catalog_settings, "night-train.png", license_state="restricted")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", visual_request())
    )
    package = service.generate_package(imported.workflow_id)
    report = json.loads(
        (catalog_settings.root / package.candidate_report_path).read_text(encoding="utf-8")
    )
    assert report["beats"][0]["state"] == "blocked_no_candidate"
    assert report["beats"][0]["candidates"] == []
    with pytest.raises(VisualWorkflowError, match="already awaits review"):
        service.generate_package(imported.workflow_id)
    engine.dispose()


def test_editorial_prose_does_not_become_search_behavior(catalog_settings: Settings) -> None:
    seed_image(catalog_settings, "night-train.png")
    document = visual_request()
    document["beats"][0]["must_have"] = ["word-that-is-not-in-the-catalog"]
    document["beats"][0]["avoid"] = ["night"]
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", document)
    )
    package = service.generate_package(imported.workflow_id)
    report = json.loads(
        (catalog_settings.root / package.candidate_report_path).read_text(encoding="utf-8")
    )
    assert report["beats"][0]["state"] == "review_required"
    engine.dispose()


def two_beat_request(*, second_repeat: bool = False, second_query: str = "missing concept") -> dict:
    document = visual_request()
    second = deepcopy(document["beats"][0])
    second["beat_id"] = "beat-002"
    second["sequence"] = 2
    second["narration_context"] = "The train disappeared beyond the hills."
    second["search_directives"][0]["query"] = second_query
    second["repeat_within_story"] = second_repeat
    document["beats"].append(second)
    return document


def test_rejected_candidate_releases_cross_beat_reservation(catalog_settings: Settings) -> None:
    asset_id = seed_image(catalog_settings, "night-train.png")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", two_beat_request())
    )
    package = service.generate_package(imported.workflow_id)
    first = json.loads(
        (catalog_settings.root / package.candidate_report_path).read_text(encoding="utf-8")
    )
    assert first["beats"][0]["candidates"][0]["asset_id"] == asset_id
    assert first["beats"][1]["state"] == "blocked_no_candidate"
    completed = complete_review(
        catalog_settings.root / package.review_template_path,
        catalog_settings.root / "combined-review.json",
        decision="replace",
        score=50,
    )
    service.import_review(imported.workflow_id, completed)
    next_package = service.generate_package(imported.workflow_id)
    second = json.loads(
        (catalog_settings.root / next_package.candidate_report_path).read_text(encoding="utf-8")
    )
    assert second["beats"][0]["state"] == "blocked_no_candidate"
    assert second["beats"][1]["candidates"][0]["asset_id"] == asset_id
    engine.dispose()


def test_repeat_within_story_allows_intentional_current_pass_reuse(
    catalog_settings: Settings,
) -> None:
    asset_id = seed_image(catalog_settings, "night-train.png")
    document = two_beat_request(second_repeat=True, second_query="night train")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", document)
    )
    package = service.generate_package(imported.workflow_id)
    report = json.loads(
        (catalog_settings.root / package.candidate_report_path).read_text(encoding="utf-8")
    )
    assert [beat["candidates"][0]["asset_id"] for beat in report["beats"]] == [
        asset_id,
        asset_id,
    ]
    engine.dispose()


def test_missing_locked_asset_is_blocked_without_editable_review(
    catalog_settings: Settings,
) -> None:
    asset_id = seed_image(catalog_settings, "night-train.png")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", visual_request())
    )
    package = service.generate_package(imported.workflow_id)
    completed = complete_review(
        catalog_settings.root / package.review_template_path,
        catalog_settings.root / "accepted.json",
        decision="accept",
    )
    service.import_review(imported.workflow_id, completed)
    with Session(engine) as session:
        asset = session.get(MediaAsset, asset_id)
        assert asset is not None
        path = catalog_settings.root / asset.relative_path
    path.unlink()
    LibraryScanner(catalog_settings, engine).scan()
    blocked_package = service.generate_package(imported.workflow_id)
    report = json.loads(
        (catalog_settings.root / blocked_package.candidate_report_path).read_text(encoding="utf-8")
    )
    template = json.loads(
        (catalog_settings.root / blocked_package.review_template_path).read_text(encoding="utf-8")
    )
    assert report["summary"]["blocked_missing"] == 1
    assert report["beats"][0]["state"] == "blocked_missing"
    assert report["beats"][0]["blocked_reason"]["code"] == "file_unavailable"
    assert template["review_entries"] == []
    with Session(engine) as session:
        selection = session.scalar(select(BeatSelection))
        beat = session.scalar(select(VisualBeat))
        assert selection is not None and selection.status == "blocked_missing"
        assert beat is not None and beat.state == "blocked_missing"
    engine.dispose()


def test_video_preview_extracts_deterministic_filmstrip(catalog_settings: Settings) -> None:
    video_path = catalog_settings.root / "Library" / "Videos" / "night-train.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=3:size=320x180:rate=10",
            "-c:v",
            "mpeg4",
            "-y",
            str(video_path),
        ],
        check=True,
        timeout=30,
    )
    engine = initialize_database(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    document = visual_request()
    document["beats"][0]["media_preference"] = "video"
    document["beats"][0]["search_directives"][0]["media_type"] = "video"
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", document)
    )
    package = service.generate_package(imported.workflow_id)
    report = json.loads(
        (catalog_settings.root / package.candidate_report_path).read_text(encoding="utf-8")
    )
    candidate = report["beats"][0]["candidates"][0]
    frames = candidate["storyboard_visuals"]["video_frames"]
    assert len(frames) == 3
    duration = candidate["technical"]["duration_ms"]
    assert [frame["timestamp_ms"] for frame in frames] == [
        round(duration * 0.10),
        round(duration * 0.50),
        round(duration * 0.90),
    ]
    assert b"STATIC VIDEO LIMITATION" in (
        catalog_settings.root / package.storyboard_path
    ).read_bytes()
    engine.dispose()


def test_known_usable_license_is_reported_as_known(catalog_settings: Settings) -> None:
    seed_image(catalog_settings, "night-train.png", license_state="known")
    engine = initialize_database(catalog_settings)
    service = VisualWorkflowService(catalog_settings, engine)
    imported = service.start_workflow(
        write_document(catalog_settings.root / "request.json", visual_request())
    )
    package = service.generate_package(imported.workflow_id)
    report = json.loads(
        (catalog_settings.root / package.candidate_report_path).read_text(encoding="utf-8")
    )
    assert report["beats"][0]["candidates"][0]["license"]["status"] == "known"
    assert (catalog_settings.root / package.storyboard_path).read_bytes().count(b"LICENSE: UNKNOWN") == 1
    engine.dispose()
