from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


EDITORIAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
MOTION_TYPES = (
    "static",
    "native",
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
)
TRANSITION_TYPES = ("cut", "cross_dissolve", "dip_to_black")
MotionType = Literal[
    "static",
    "native",
    "slow_zoom_in",
    "slow_zoom_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
]
TransitionType = Literal["cut", "cross_dissolve", "dip_to_black"]


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SfxRecommendation(PlanModel):
    type: Literal["sfx"] = "sfx"
    purpose: str = Field(min_length=1)
    sfx_kind: Literal["one_shot", "ambient"]
    desired_sound: str = Field(min_length=1)
    search_queries: tuple[str, ...] = Field(min_length=1)
    intensity: str = Field(min_length=1)
    note: str | None = None

    @field_validator("search_queries")
    @classmethod
    def nonempty_search_queries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("SFX search queries cannot be empty")
        return value


class ProductionOpportunity(PlanModel):
    trigger: str = Field(min_length=1)
    sfx_suggestion: str | None = None
    sfx_recommendation: SfxRecommendation | None = None
    edit_suggestion: str | None = None

    @model_validator(mode="after")
    def has_actual_suggestion(self) -> "ProductionOpportunity":
        if not self.sfx_suggestion and not self.sfx_recommendation and not self.edit_suggestion:
            raise ValueError(
                "a production opportunity requires an SFX or edit suggestion"
            )
        return self


class VisualPlanStory(PlanModel):
    story_id: str
    title: str = Field(min_length=1)

    @field_validator("story_id")
    @classmethod
    def valid_story_id(cls, value: str) -> str:
        if not EDITORIAL_ID.fullmatch(value):
            raise ValueError("story_id must be a stable lowercase editorial identifier")
        return value


class VisualPlanBeat(PlanModel):
    beat_id: str
    sequence: int = Field(ge=1)
    narration_context: str = Field(min_length=1)
    desired_visual: str = Field(min_length=1)
    search_queries: tuple[str, ...] = Field(min_length=1)
    must_have: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    media_preference: Literal["image", "video", "either"]
    source_requirement: Literal["representative", "exact"]
    production_opportunities: tuple[ProductionOpportunity, ...] = ()

    @field_validator("beat_id")
    @classmethod
    def valid_beat_id(cls, value: str) -> str:
        if not EDITORIAL_ID.fullmatch(value):
            raise ValueError("beat_id must be a stable lowercase editorial identifier")
        return value

    @field_validator("search_queries")
    @classmethod
    def nonempty_search_queries(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("search queries cannot be empty")
        return value

    @field_validator("must_have", "avoid")
    @classmethod
    def nonempty_guidance(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("guidance entries cannot be empty")
        return value


class VisualPlan(PlanModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        title="Visual Plan v1",
        json_schema_extra={
            "$id": "https://yt-visuals.local/schemas/visual-plan.v1.schema.json",
            "$schema": "https://json-schema.org/draft/2020-12/schema",
        },
    )

    document_type: Literal["visual_plan"]
    contract_version: Literal[1]
    story: VisualPlanStory
    beats: tuple[VisualPlanBeat, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_beats_and_sequences(self) -> "VisualPlan":
        beat_ids = [beat.beat_id for beat in self.beats]
        sequences = [beat.sequence for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("beat IDs must be unique")
        if len(sequences) != len(set(sequences)):
            raise ValueError("beat sequences must be unique")
        return self

    def canonical_bytes(self) -> bytes:
        value = self.model_dump(mode="json")
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def document_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def validate_visual_plan_file(path: Path) -> VisualPlan:
    return VisualPlan.model_validate_json(path.read_text(encoding="utf-8"))


class EditPlanStory(PlanModel):
    story_id: str

    @field_validator("story_id")
    @classmethod
    def valid_story_id(cls, value: str) -> str:
        if not EDITORIAL_ID.fullmatch(value):
            raise ValueError("story_id must be a stable lowercase editorial identifier")
        return value


class MotionRecommendation(PlanModel):
    type: MotionType
    purpose: str = Field(min_length=1)
    target: str | None

    @field_validator("target")
    @classmethod
    def nonempty_target(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("motion target must be null or non-empty")
        return value


class TransitionOutRecommendation(PlanModel):
    type: TransitionType
    to_beat_id: str
    purpose: str = Field(min_length=1)

    @field_validator("to_beat_id")
    @classmethod
    def valid_to_beat_id(cls, value: str) -> str:
        if not EDITORIAL_ID.fullmatch(value):
            raise ValueError("to_beat_id must be a stable lowercase editorial identifier")
        return value


class EditPlanBeat(PlanModel):
    beat_id: str
    sequence: int = Field(ge=1)
    motion_recommendation: MotionRecommendation
    transition_out_recommendation: TransitionOutRecommendation | None

    @field_validator("beat_id")
    @classmethod
    def valid_beat_id(cls, value: str) -> str:
        if not EDITORIAL_ID.fullmatch(value):
            raise ValueError("beat_id must be a stable lowercase editorial identifier")
        return value


class EditPlan(PlanModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        title="Edit Plan v1",
    )

    document_type: Literal["edit_plan"]
    contract_version: Literal[1]
    story: EditPlanStory
    beats: tuple[EditPlanBeat, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_beat_chain(self) -> "EditPlan":
        beat_ids = [beat.beat_id for beat in self.beats]
        sequences = [beat.sequence for beat in self.beats]
        if len(beat_ids) != len(set(beat_ids)):
            raise ValueError("beat IDs must be unique")
        if len(sequences) != len(set(sequences)):
            raise ValueError("beat sequences must be unique")
        for index, beat in enumerate(self.beats):
            transition = beat.transition_out_recommendation
            if index == len(self.beats) - 1:
                if transition is not None:
                    raise ValueError("the final beat transition must be null")
                continue
            if transition is None:
                raise ValueError("every non-final beat requires a transition recommendation")
            if transition.to_beat_id != self.beats[index + 1].beat_id:
                raise ValueError("transition to_beat_id must be the immediately following beat")
        return self

    def canonical_bytes(self) -> bytes:
        value = self.model_dump(mode="json")
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def document_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def validate_edit_plan_file(path: Path) -> EditPlan:
    return EditPlan.model_validate_json(path.read_text(encoding="utf-8"))
