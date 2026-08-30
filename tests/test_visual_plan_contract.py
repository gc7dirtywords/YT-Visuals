from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from yt_visuals.producer.contracts import VisualPlan, validate_visual_plan_file


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _plan() -> dict:
    return {
        "document_type": "visual_plan",
        "contract_version": 1,
        "story": {"story_id": "producer-story", "title": "Producer Story"},
        "beats": [
            {
                "beat_id": "beat-001",
                "sequence": 1,
                "narration_context": "A door slams in the empty hall.",
                "desired_visual": "An empty dark hallway",
                "search_queries": ["empty dark hallway"],
                "must_have": ["hallway"],
                "avoid": ["visible people"],
                "media_preference": "either",
                "source_requirement": "representative",
                "production_opportunities": [
                    {
                        "trigger": "the door slams",
                        "sfx_suggestion": "One restrained door impact",
                        "edit_suggestion": None,
                    }
                ],
            },
            {
                "beat_id": "beat-002",
                "sequence": 2,
                "narration_context": "The handle slowly turns.",
                "desired_visual": "A close view of an old door handle",
                "search_queries": ["old door handle close up"],
                "must_have": [],
                "avoid": [],
                "media_preference": "image",
                "source_requirement": "exact",
                "production_opportunities": [],
            },
        ],
    }


def test_visual_plan_v1_validates_and_example_fixture_is_current() -> None:
    plan = VisualPlan.model_validate(_plan())
    assert plan.document_type == "visual_plan"
    assert plan.contract_version == 1
    assert plan.beats[0].production_opportunities[0].trigger == "the door slams"
    fixture = validate_visual_plan_file(REPOSITORY_ROOT / "examples/visual-plan.v1.json")
    assert fixture.story.story_id == "example-fireplace-story"


@pytest.mark.parametrize("duplicate_field", ["beat_id", "sequence"])
def test_duplicate_beat_ids_and_sequences_are_rejected(duplicate_field: str) -> None:
    document = _plan()
    document["beats"][1][duplicate_field] = document["beats"][0][duplicate_field]
    with pytest.raises(ValidationError, match="must be unique"):
        VisualPlan.model_validate(document)


def test_search_queries_and_production_opportunities_require_real_content() -> None:
    document = _plan()
    document["beats"][0]["search_queries"] = [""]
    with pytest.raises(ValidationError, match="search queries cannot be empty"):
        VisualPlan.model_validate(document)

    document = deepcopy(_plan())
    document["beats"][0]["production_opportunities"][0] = {
        "trigger": "door slams",
        "sfx_suggestion": None,
        "edit_suggestion": None,
    }
    with pytest.raises(ValidationError, match="requires an SFX or edit suggestion"):
        VisualPlan.model_validate(document)


def test_structured_sfx_recommendation_is_optional_and_backward_compatible() -> None:
    document = _plan()
    document["beats"][0]["production_opportunities"] = [{
        "trigger": "the chest shifts away from the wall",
        "sfx_recommendation": {
            "type": "sfx",
            "purpose": "Attention reset for an unexpected reveal",
            "sfx_kind": "one_shot",
            "desired_sound": "restrained low tonal accent",
            "search_queries": ["subtle dark tonal hit", "restrained impact"],
            "intensity": "subtle",
            "note": "Do not literalize the narration.",
        },
    }]
    plan = VisualPlan.model_validate(document)
    recommendation = plan.beats[0].production_opportunities[0].sfx_recommendation
    assert recommendation is not None
    assert recommendation.sfx_kind == "one_shot"
    assert recommendation.search_queries == (
        "subtle dark tonal hit", "restrained impact"
    )
    assert VisualPlan.model_validate(_plan()).beats[0].production_opportunities[0].sfx_suggestion
