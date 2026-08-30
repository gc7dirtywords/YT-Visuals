from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from yt_visuals.producer.contracts import EditPlan


def edit_plan_document() -> dict:
    return {
        "document_type": "edit_plan",
        "contract_version": 1,
        "story": {"story_id": "producer-story"},
        "beats": [
            {
                "beat_id": "beat-001",
                "sequence": 1,
                "motion_recommendation": {
                    "type": "slow_zoom_in",
                    "purpose": "Draw attention toward the fireplace.",
                    "target": "fireplace",
                },
                "transition_out_recommendation": {
                    "type": "cross_dissolve",
                    "to_beat_id": "beat-002",
                    "purpose": "Ease into the silent room.",
                },
            },
            {
                "beat_id": "beat-002",
                "sequence": 2,
                "motion_recommendation": {
                    "type": "static",
                    "purpose": "Hold on the empty room.",
                    "target": None,
                },
                "transition_out_recommendation": None,
            },
        ],
    }


def test_edit_plan_v1_accepts_exact_contract_and_hashes_canonically() -> None:
    plan = EditPlan.model_validate(edit_plan_document())
    assert plan.document_type == "edit_plan"
    assert plan.beats[0].motion_recommendation.type == "slow_zoom_in"
    assert len(plan.document_sha256()) == 64


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("beats", 0, "motion_recommendation", "type"), "push_in"),
        (("beats", 0, "transition_out_recommendation", "type"), "wipe"),
        (("beats", 0, "motion_recommendation", "target"), ""),
    ],
)
def test_edit_plan_rejects_values_outside_exact_contract(path: tuple, value: object) -> None:
    document = deepcopy(edit_plan_document())
    cursor = document
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(ValidationError):
        EditPlan.model_validate(document)


def test_edit_plan_rejects_extra_fields_and_invalid_transition_chain() -> None:
    document = edit_plan_document()
    document["beats"][0]["editor_note"] = "not in v1"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EditPlan.model_validate(document)

    document = edit_plan_document()
    document["beats"][0]["transition_out_recommendation"]["to_beat_id"] = "beat-001"
    with pytest.raises(ValidationError, match="immediately following beat"):
        EditPlan.model_validate(document)

    document = edit_plan_document()
    document["beats"][1]["transition_out_recommendation"] = {
        "type": "cut",
        "to_beat_id": "beat-001",
        "purpose": "Invalid final transition.",
    }
    with pytest.raises(ValidationError, match="final beat transition must be null"):
        EditPlan.model_validate(document)
