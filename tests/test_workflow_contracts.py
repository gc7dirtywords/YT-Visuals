from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from yt_visuals.workflow.contracts import (
    VisualRequest,
    VisualReviewDocument,
    VisualReviewDocumentV2,
    validate_visual_review_document,
    compatibility_fingerprint,
)


def request_document() -> dict:
    return {
        "document_type": "visual_request",
        "contract_version": 1,
        "story": {
            "story_id": "story-night-train",
            "title": "The Night Train",
            "target_duration_ms": 360_000,
            "presentation_profile": "calm_late_night_second_monitor_v1",
        },
        "beats": [
            {
                "beat_id": "beat-001",
                "sequence": 1,
                "timing": {"start_ms": 0, "end_ms": 20_000, "precision": "estimated"},
                "narration_context": "The train crossed the sleeping countryside.",
                "desired_visual": {
                    "summary": "A distant train moving through a quiet nocturnal landscape",
                    "subjects": ["train", "landscape"],
                    "setting": "rural countryside",
                    "mood": "calm",
                },
                "media_preference": "either",
                "search_concepts": ["night train"],
                "search_directives": [
                    {
                        "query": "night train",
                        "media_type": "either",
                        "required_terms": [],
                        "excluded_terms": ["daylight"],
                        "filters": {"orientation": "landscape"},
                    }
                ],
                "must_have": ["night setting", "visible train"],
                "preferred": ["wide composition"],
                "avoid": ["busy station"],
                "technical_constraints": {"orientation": "landscape"},
            }
        ],
    }


def replacement_guidance() -> dict:
    return {
        "summary": "Search for a darker and wider exterior.",
        "must_have": ["train"],
        "preferred": ["moonlight"],
        "avoid": ["station"],
        "revised_search_directives": [
            {
                "query": "train moonlight",
                "media_type": "image",
                "required_terms": [],
                "excluded_terms": [],
                "filters": {"orientation": "landscape"},
            }
        ],
        "media_preference_change": "image",
        "external_sourcing_allowed": False,
    }


def completed_review(score: int, decision: str) -> dict:
    guidance = replacement_guidance() if decision == "replace" else None
    return {
        "document_type": "visual_review",
        "contract_version": 1,
        "bookkeeping": {
            "workflow_id": "00000000-0000-0000-0000-000000000001",
            "request_id": "00000000-0000-0000-0000-000000000002",
            "request_revision": 1,
            "request_document_sha256": "a" * 64,
            "package_id": "00000000-0000-0000-0000-000000000003",
            "candidate_report_sha256": "b" * 64,
            "storyboard_pdf_sha256": "c" * 64,
            "review_id": "00000000-0000-0000-0000-000000000004",
            "iteration": 1,
        },
        "story": {"story_id": "story-night-train"},
        "review_entries": [
            {
                "entry_type": "candidate_review",
                "beat_id": "beat-001",
                "sequence": 1,
                "candidate": {
                    "candidate_id": "00000000-0000-0000-0000-000000000005",
                    "asset_id": 1,
                    "asset_sha256": "d" * 64,
                },
                "editorial_review": {
                    "alignment_score": score,
                    "decision": decision,
                    "mismatch_reasons": (
                        [{"category": "mood", "explanation": "The image is too bright."}]
                        if decision == "replace"
                        else []
                    ),
                    "mismatch_explanation": None,
                    "replacement_guidance": guidance,
                    "catalog_annotations": None,
                },
            }
        ],
    }


def test_visual_request_defaults_and_no_operational_fields() -> None:
    request = VisualRequest.model_validate(request_document())
    beat = request.beats[0]
    assert beat.prior_usage_policy == "prefer_unused"
    assert beat.repeat_within_story is False
    payload = request.model_dump(mode="json")
    assert "workflow_id" not in payload
    assert "request_id" not in payload
    assert "sha256" not in str(payload).lower()
    assert "created_at" not in payload


def test_contracts_reject_unknown_fields_and_unsupported_versions() -> None:
    unknown = request_document()
    unknown["prompt"] = "not allowed"
    with pytest.raises(ValidationError, match="Extra inputs"):
        VisualRequest.model_validate(unknown)
    unsupported = request_document()
    unsupported["contract_version"] = 2
    with pytest.raises(ValidationError):
        VisualRequest.model_validate(unsupported)


def test_compatibility_fingerprint_ignores_timing_sequence_and_search() -> None:
    original = VisualRequest.model_validate(request_document()).beats[0]
    changed = request_document()["beats"][0]
    changed["sequence"] = 99
    changed["timing"] = {"start_ms": 50_000, "end_ms": 60_000, "precision": "exact"}
    changed["narration_context"] = "Different context"
    changed["search_concepts"] = ["different concept"]
    changed["search_directives"][0]["query"] = "different explicit query"
    revised = original.model_validate(changed)
    assert compatibility_fingerprint(original) == compatibility_fingerprint(revised)


def test_compatibility_fingerprint_is_set_order_independent_and_visual_sensitive() -> None:
    document = request_document()
    original = VisualRequest.model_validate(document).beats[0]
    reordered = deepcopy(document["beats"][0])
    reordered["must_have"] = ["visible train", "night setting", "visible train"]
    assert compatibility_fingerprint(original) == compatibility_fingerprint(original.model_validate(reordered))
    changed = deepcopy(document["beats"][0])
    changed["desired_visual"]["summary"] = "A close-up locomotive at noon"
    assert compatibility_fingerprint(original) != compatibility_fingerprint(original.model_validate(changed))


def test_alignment_threshold_and_replacement_rules() -> None:
    with pytest.raises(ValidationError):
        VisualReviewDocument.model_validate(completed_review(89, "accept"))
    accepted = VisualReviewDocument.model_validate(completed_review(90, "accept"))
    assert accepted.review_entries[0].editorial_review.decision == "accept"
    replaced = VisualReviewDocument.model_validate(completed_review(90, "replace"))
    assert replaced.review_entries[0].editorial_review.replacement_guidance is not None
    missing_guidance = completed_review(75, "replace")
    missing_guidance["review_entries"][0]["editorial_review"]["replacement_guidance"] = None
    with pytest.raises(ValidationError):
        VisualReviewDocument.model_validate(missing_guidance)


def test_v2_adds_only_external_blocked_reasons_and_v1_still_imports() -> None:
    assert isinstance(validate_visual_review_document(completed_review(95, "accept")), VisualReviewDocument)
    document = completed_review(95, "accept")
    document["contract_version"] = 2
    assert isinstance(validate_visual_review_document(document), VisualReviewDocumentV2)
    blocked = deepcopy(document)
    blocked["review_entries"] = [{
        "entry_type": "blocked_beat_guidance", "beat_id": "beat-001", "sequence": 1,
        "blocked_reason": {
            "code": "no_external_provider_matches",
            "explanation": "No Pexels results were returned.",
        },
        "editorial_guidance": {
            "action": "revise_search", "replacement_guidance": replacement_guidance(),
        },
    }]
    assert isinstance(validate_visual_review_document(blocked), VisualReviewDocumentV2)
    blocked["contract_version"] = 1
    with pytest.raises(ValidationError):
        VisualReviewDocument.model_validate(blocked)
