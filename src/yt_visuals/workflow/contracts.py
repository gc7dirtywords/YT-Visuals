from __future__ import annotations

import hashlib
import json
import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator


EDITORIAL_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    def json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class Timing(ContractModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    precision: Literal["exact", "estimated"]

    @model_validator(mode="after")
    def end_after_start(self) -> "Timing":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class DesiredVisual(ContractModel):
    summary: str = Field(min_length=1)
    subjects: tuple[str, ...] = ()
    setting: str | None = None
    historical_era: str | None = None
    mood: str | None = None
    composition: str | None = None


class SearchFilters(ContractModel):
    orientation: Literal["landscape", "portrait", "square"] | None = None
    minimum_width: int | None = Field(default=None, gt=0)
    minimum_height: int | None = Field(default=None, gt=0)
    minimum_duration_ms: int | None = Field(default=None, ge=0)
    maximum_duration_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_duration(self) -> "SearchFilters":
        if (
            self.minimum_duration_ms is not None
            and self.maximum_duration_ms is not None
            and self.maximum_duration_ms < self.minimum_duration_ms
        ):
            raise ValueError("maximum_duration_ms must be >= minimum_duration_ms")
        return self


class SearchDirective(ContractModel):
    query: str = Field(min_length=1)
    media_type: Literal["image", "video", "either"]
    required_terms: tuple[str, ...] = ()
    excluded_terms: tuple[str, ...] = ()
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @model_validator(mode="after")
    def nonempty_terms(self) -> "SearchDirective":
        if any(not value for value in (*self.required_terms, *self.excluded_terms)):
            raise ValueError("search terms cannot be empty")
        return self


class VideoDuration(ContractModel):
    minimum: int | None = Field(default=None, ge=0)
    maximum: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def valid_range(self) -> "VideoDuration":
        if self.minimum is not None and self.maximum is not None and self.maximum < self.minimum:
            raise ValueError("maximum must be >= minimum")
        return self


class TechnicalConstraints(ContractModel):
    orientation: Literal["any", "landscape", "portrait", "square"] = "any"
    minimum_width: int | None = Field(default=None, gt=0)
    minimum_height: int | None = Field(default=None, gt=0)
    video_duration_ms: VideoDuration | None = None


class VisualBeat(ContractModel):
    beat_id: str
    sequence: int = Field(ge=1)
    timing: Timing | None
    narration_context: str = Field(min_length=1)
    desired_visual: DesiredVisual
    media_preference: Literal["image", "video", "either"]
    search_concepts: tuple[str, ...] = Field(min_length=1)
    search_directives: tuple[SearchDirective, ...] = Field(min_length=1)
    must_have: tuple[str, ...] = ()
    preferred: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    prior_usage_policy: Literal[
        "prefer_unused", "allow_prior_usage", "forbid_prior_usage"
    ] = "prefer_unused"
    repeat_within_story: bool = False
    technical_constraints: TechnicalConstraints = Field(default_factory=TechnicalConstraints)

    @field_validator("beat_id")
    @classmethod
    def valid_beat_id(cls, value: str) -> str:
        if not EDITORIAL_ID.fullmatch(value):
            raise ValueError("beat_id must be a stable lowercase editorial identifier")
        return value


class StoryRequest(ContractModel):
    story_id: str
    title: str = Field(min_length=1)
    target_duration_ms: int | None = Field(default=None, gt=0)
    presentation_profile: Literal["calm_late_night_second_monitor_v1"]

    @field_validator("story_id")
    @classmethod
    def valid_story_id(cls, value: str) -> str:
        if not EDITORIAL_ID.fullmatch(value):
            raise ValueError("story_id must be a stable lowercase editorial identifier")
        return value


class VisualRequest(ContractModel):
    document_type: Literal["visual_request"]
    contract_version: Literal[1]
    story: StoryRequest
    beats: tuple[VisualBeat, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_beats(self) -> "VisualRequest":
        ids = [beat.beat_id for beat in self.beats]
        sequences = [beat.sequence for beat in self.beats]
        if len(ids) != len(set(ids)):
            raise ValueError("beat_id values must be unique")
        if sequences != list(range(1, len(self.beats) + 1)):
            raise ValueError("beat sequence values must be contiguous and ordered from 1")
        starts = [beat.timing.start_ms for beat in self.beats if beat.timing]
        if starts != sorted(starts):
            raise ValueError("timed beat starts must be nondecreasing")
        if self.story.target_duration_ms is not None:
            for beat in self.beats:
                if beat.timing and beat.timing.end_ms > self.story.target_duration_ms:
                    raise ValueError(f"beat {beat.beat_id} exceeds target story duration")
        return self


class ReplacementGuidance(ContractModel):
    summary: str = Field(min_length=1)
    must_have: tuple[str, ...] = ()
    preferred: tuple[str, ...] = ()
    avoid: tuple[str, ...] = ()
    revised_search_directives: tuple[SearchDirective, ...] = Field(min_length=1)
    media_preference_change: Literal["image", "video", "either"] | None = None
    external_sourcing_allowed: bool


class MismatchReason(ContractModel):
    category: Literal[
        "subject", "narrative_relevance", "setting", "historical_era", "mood",
        "composition", "presentation_style", "media_type", "duration",
        "technical_quality", "repetition", "licensing", "other",
    ]
    explanation: str = Field(min_length=1)


class CatalogAnnotations(ContractModel):
    descriptive_tags: tuple[str, ...] = ()
    visual_concepts: tuple[str, ...] = ()
    historical_era: str | None = None
    setting: str | None = None
    moods: tuple[str, ...] = ()


class ReviewBookkeeping(ContractModel):
    workflow_id: str
    request_id: str
    request_revision: int = Field(ge=1)
    request_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_id: str
    candidate_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    storyboard_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review_id: str
    iteration: int = Field(ge=1)


class ReviewStory(ContractModel):
    story_id: str


class CandidateReference(ContractModel):
    candidate_id: str
    asset_id: int = Field(gt=0)
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BlankCandidateEditorialReview(ContractModel):
    alignment_score: None
    decision: None
    mismatch_reasons: tuple[()] = ()
    mismatch_explanation: None
    replacement_guidance: None
    catalog_annotations: None


class CompletedCandidateEditorialReview(ContractModel):
    alignment_score: int = Field(ge=0, le=100)
    decision: Literal["accept", "replace"]
    mismatch_reasons: tuple[MismatchReason, ...] = ()
    mismatch_explanation: str | None = None
    replacement_guidance: ReplacementGuidance | None
    catalog_annotations: CatalogAnnotations | None = None

    @model_validator(mode="after")
    def decision_rules(self) -> "CompletedCandidateEditorialReview":
        if self.alignment_score < 90 and self.decision != "replace":
            raise ValueError("alignment scores below 90 must be replaced")
        if self.decision == "accept":
            if self.alignment_score < 90:
                raise ValueError("accept requires alignment_score >= 90")
            if self.replacement_guidance is not None:
                raise ValueError("accepted candidates cannot include replacement guidance")
        else:
            if not self.mismatch_reasons and not self.mismatch_explanation:
                raise ValueError("replacement requires meaningful mismatch information")
            if self.replacement_guidance is None:
                raise ValueError("replacement requires replacement guidance")
            if self.catalog_annotations is not None:
                raise ValueError("catalog annotations are allowed only on accepted candidates")
        return self


class BlockedReason(ContractModel):
    code: Literal[
        "no_local_matches", "all_matches_excluded",
        "no_technically_eligible_matches", "preview_generation_failed",
    ]
    explanation: str = Field(min_length=1)


class BlankBlockedGuidance(ContractModel):
    action: None
    replacement_guidance: None


class CompletedBlockedGuidance(ContractModel):
    action: Literal["revise_search"]
    replacement_guidance: ReplacementGuidance


class CandidateReviewTemplateEntry(ContractModel):
    entry_type: Literal["candidate_review"]
    beat_id: str
    sequence: int = Field(ge=1)
    candidate: CandidateReference
    editorial_review: BlankCandidateEditorialReview


class BlockedGuidanceTemplateEntry(ContractModel):
    entry_type: Literal["blocked_beat_guidance"]
    beat_id: str
    sequence: int = Field(ge=1)
    blocked_reason: BlockedReason
    editorial_guidance: BlankBlockedGuidance


TemplateEntry = Annotated[
    CandidateReviewTemplateEntry | BlockedGuidanceTemplateEntry,
    Field(discriminator="entry_type"),
]


class VisualReviewTemplate(ContractModel):
    document_type: Literal["visual_review"]
    contract_version: Literal[1]
    bookkeeping: ReviewBookkeeping
    story: ReviewStory
    review_entries: tuple[TemplateEntry, ...]

    @model_validator(mode="after")
    def unique_entries(self) -> "VisualReviewTemplate":
        _validate_review_entry_identity(self.review_entries)
        return self


class CompletedCandidateReviewEntry(ContractModel):
    entry_type: Literal["candidate_review"]
    beat_id: str
    sequence: int = Field(ge=1)
    candidate: CandidateReference
    editorial_review: CompletedCandidateEditorialReview


class CompletedBlockedGuidanceEntry(ContractModel):
    entry_type: Literal["blocked_beat_guidance"]
    beat_id: str
    sequence: int = Field(ge=1)
    blocked_reason: BlockedReason
    editorial_guidance: CompletedBlockedGuidance


class BlockedReasonV2(ContractModel):
    code: Literal[
        "no_local_matches", "all_matches_excluded",
        "no_technically_eligible_matches", "preview_generation_failed",
        "no_external_provider_matches", "all_external_provider_matches_excluded",
        "no_external_provider_technically_eligible_matches",
    ]
    explanation: str = Field(min_length=1)


class BlockedGuidanceTemplateEntryV2(ContractModel):
    entry_type: Literal["blocked_beat_guidance"]
    beat_id: str
    sequence: int = Field(ge=1)
    blocked_reason: BlockedReasonV2
    editorial_guidance: BlankBlockedGuidance


class CompletedBlockedGuidanceEntryV2(ContractModel):
    entry_type: Literal["blocked_beat_guidance"]
    beat_id: str
    sequence: int = Field(ge=1)
    blocked_reason: BlockedReasonV2
    editorial_guidance: CompletedBlockedGuidance


CompletedReviewEntry = Annotated[
    CompletedCandidateReviewEntry | CompletedBlockedGuidanceEntry,
    Field(discriminator="entry_type"),
]


class VisualReviewDocument(ContractModel):
    document_type: Literal["visual_review"]
    contract_version: Literal[1]
    bookkeeping: ReviewBookkeeping
    story: ReviewStory
    review_entries: tuple[CompletedReviewEntry, ...]

    @model_validator(mode="after")
    def unique_entries(self) -> "VisualReviewDocument":
        _validate_review_entry_identity(self.review_entries)
        return self


TemplateEntryV2 = Annotated[
    CandidateReviewTemplateEntry | BlockedGuidanceTemplateEntryV2,
    Field(discriminator="entry_type"),
]


CompletedReviewEntryV2 = Annotated[
    CompletedCandidateReviewEntry | CompletedBlockedGuidanceEntryV2,
    Field(discriminator="entry_type"),
]


class VisualReviewTemplateV2(ContractModel):
    document_type: Literal["visual_review"]
    contract_version: Literal[2]
    bookkeeping: ReviewBookkeeping
    story: ReviewStory
    review_entries: tuple[TemplateEntryV2, ...]

    @model_validator(mode="after")
    def unique_entries(self) -> "VisualReviewTemplateV2":
        _validate_review_entry_identity(self.review_entries)
        return self


class VisualReviewDocumentV2(ContractModel):
    document_type: Literal["visual_review"]
    contract_version: Literal[2]
    bookkeeping: ReviewBookkeeping
    story: ReviewStory
    review_entries: tuple[CompletedReviewEntryV2, ...]

    @model_validator(mode="after")
    def unique_entries(self) -> "VisualReviewDocumentV2":
        _validate_review_entry_identity(self.review_entries)
        return self


class ReportStory(ContractModel):
    story_id: str
    title: str


class ReportSummary(ContractModel):
    total_beats: int = Field(ge=1)
    review_required: int = Field(ge=0)
    locked_accepted: int = Field(ge=0)
    blocked_no_candidate: int = Field(ge=0)
    blocked_missing: int = Field(ge=0)


class ExpectedArtifact(ContractModel):
    relative_path: str


class ReportRequestSnapshot(ContractModel):
    timing: Timing | None
    narration_context: str
    desired_visual: DesiredVisual
    media_preference: Literal["image", "video", "either"]
    search_concepts: tuple[str, ...]
    search_directives: tuple[SearchDirective, ...]
    must_have: tuple[str, ...]
    preferred: tuple[str, ...]
    avoid: tuple[str, ...]
    prior_usage_policy: Literal[
        "prefer_unused", "allow_prior_usage", "forbid_prior_usage"
    ]
    repeat_within_story: bool
    technical_constraints: TechnicalConstraints


class ReportTechnical(ContractModel):
    mime_type: str | None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    duration_ms: int | None = Field(default=None, ge=0)
    file_size_bytes: int = Field(ge=0)


class ReportProvenance(ContractModel):
    origin: Literal["local_import", "provider_download"]
    provider: str | None
    provider_asset_id: str | None
    source_url: str | None
    creator_name: str | None
    creator_url: str | None


class ReportLicense(ContractModel):
    status: Literal["known", "unknown", "restricted"]
    license_name: str | None
    license_url: str | None
    attribution_required: bool | None
    attribution_text: str | None
    commercial_use_allowed: bool | None
    modifications_allowed: bool | None


class ReportUsage(ContractModel):
    usage_count: int = Field(ge=0)
    last_used_at: str | None
    recent_usage_references: tuple[str, ...]


class ReportRetrieval(ContractModel):
    stage: Literal["local"]
    query: str
    rank: int = Field(ge=1)
    retrieval_score: int
    score_reasons: tuple[str, ...]


class VideoFrame(ContractModel):
    relative_path: str
    timestamp_ms: int = Field(ge=0)


class StoryboardVisuals(ContractModel):
    poster_frame_path: str
    video_frames: tuple[VideoFrame, ...]


class ReportCandidate(ContractModel):
    candidate_id: str
    asset_id: int = Field(gt=0)
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["image", "video"]
    catalog_status: Literal["existing_local", "previously_downloaded", "newly_downloaded"]
    relative_path: str
    available: bool
    technical: ReportTechnical
    provenance: ReportProvenance
    license: ReportLicense
    usage: ReportUsage
    retrieval: ReportRetrieval
    storyboard_visuals: StoryboardVisuals


class ReportLock(ContractModel):
    review_id: str
    candidate_id: str
    asset_id: int = Field(gt=0)
    asset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    alignment_score: int = Field(ge=90, le=100)
    locked_at: str


class ReportBlockedReason(ContractModel):
    code: Literal[
        "no_local_matches", "all_matches_excluded",
        "no_technically_eligible_matches", "preview_generation_failed",
        "file_unavailable", "asset_hash_mismatch", "catalog_identity_mismatch",
    ]
    explanation: str


class CandidateReportBeat(ContractModel):
    beat_id: str
    sequence: int = Field(ge=1)
    state: Literal[
        "review_required", "locked_accepted", "blocked_no_candidate", "blocked_missing"
    ]
    request_snapshot: ReportRequestSnapshot
    candidates: tuple[ReportCandidate, ...] = Field(max_length=1)
    blocked_reason: ReportBlockedReason | None
    lock: ReportLock | None

    @model_validator(mode="after")
    def state_shape(self) -> "CandidateReportBeat":
        count = len(self.candidates)
        if self.state == "review_required":
            if count != 1 or self.blocked_reason is not None or self.lock is not None:
                raise ValueError("review_required requires exactly one candidate and no block or lock")
        elif self.state == "locked_accepted":
            if count != 1 or self.blocked_reason is not None or self.lock is None:
                raise ValueError("locked_accepted requires exactly one candidate and a lock")
        elif self.state == "blocked_no_candidate":
            if count != 0 or self.blocked_reason is None or self.lock is not None:
                raise ValueError("blocked_no_candidate requires a reason and no candidate or lock")
        elif self.blocked_reason is None or self.lock is None:
            raise ValueError("blocked_missing requires a deterministic reason and retained lock")
        return self


class CandidateReport(ContractModel):
    document_type: Literal["candidate_report"]
    contract_version: Literal[1]
    workflow_id: str
    request_id: str
    request_revision: int = Field(ge=1)
    request_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_id: str
    review_id: str
    iteration: int = Field(ge=1)
    generated_at: str
    story: ReportStory
    review_threshold: Literal[90]
    expected_storyboard: ExpectedArtifact
    expected_review_template: ExpectedArtifact
    summary: ReportSummary
    beats: tuple[CandidateReportBeat, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_beats(self) -> "CandidateReport":
        ids = [beat.beat_id for beat in self.beats]
        sequences = [beat.sequence for beat in self.beats]
        if len(ids) != len(set(ids)):
            raise ValueError("Candidate Report beat IDs must be unique")
        if sequences != list(range(1, len(self.beats) + 1)):
            raise ValueError("Candidate Report beat sequences must be contiguous and ordered")
        expected = {
            "total_beats": len(self.beats),
            "review_required": sum(beat.state == "review_required" for beat in self.beats),
            "locked_accepted": sum(beat.state == "locked_accepted" for beat in self.beats),
            "blocked_no_candidate": sum(beat.state == "blocked_no_candidate" for beat in self.beats),
            "blocked_missing": sum(beat.state == "blocked_missing" for beat in self.beats),
        }
        if self.summary.model_dump() != expected:
            raise ValueError("Candidate Report summary does not match beat states")
        return self


class ReportBlockedReasonV2(ContractModel):
    code: Literal[
        "no_local_matches", "all_matches_excluded",
        "no_technically_eligible_matches", "preview_generation_failed",
        "no_external_provider_matches", "all_external_provider_matches_excluded",
        "no_external_provider_technically_eligible_matches",
        "file_unavailable", "asset_hash_mismatch", "catalog_identity_mismatch",
    ]
    explanation: str


class CandidateReportBeatV2(ContractModel):
    beat_id: str
    sequence: int = Field(ge=1)
    state: Literal[
        "review_required", "locked_accepted", "blocked_no_candidate", "blocked_missing"
    ]
    request_snapshot: ReportRequestSnapshot
    candidates: tuple[ReportCandidate, ...] = Field(max_length=1)
    blocked_reason: ReportBlockedReasonV2 | None
    lock: ReportLock | None

    @model_validator(mode="after")
    def state_shape(self) -> "CandidateReportBeatV2":
        _validate_report_beat_shape(self)
        return self


class CandidateReportV2(ContractModel):
    document_type: Literal["candidate_report"]
    contract_version: Literal[2]
    workflow_id: str
    request_id: str
    request_revision: int = Field(ge=1)
    request_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    package_id: str
    review_id: str
    iteration: int = Field(ge=1)
    generated_at: str
    story: ReportStory
    review_threshold: Literal[90]
    expected_storyboard: ExpectedArtifact
    expected_review_template: ExpectedArtifact
    summary: ReportSummary
    beats: tuple[CandidateReportBeatV2, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent_beats(self) -> "CandidateReportV2":
        _validate_candidate_report(self)
        return self


def _validate_review_entry_identity(entries: tuple[Any, ...]) -> None:
    identities = [(entry.beat_id, entry.sequence) for entry in entries]
    if len(identities) != len(set(identities)):
        raise ValueError("review entry beat identities must be unique")
    sequences = [entry.sequence for entry in entries]
    if sequences != sorted(sequences):
        raise ValueError("review entries must remain in beat sequence order")


def _validate_report_beat_shape(beat: Any) -> None:
    count = len(beat.candidates)
    if beat.state == "review_required":
        if count != 1 or beat.blocked_reason is not None or beat.lock is not None:
            raise ValueError("review_required requires exactly one candidate and no block or lock")
    elif beat.state == "locked_accepted":
        if count != 1 or beat.blocked_reason is not None or beat.lock is None:
            raise ValueError("locked_accepted requires exactly one candidate and a lock")
    elif beat.state == "blocked_no_candidate":
        if count != 0 or beat.blocked_reason is None or beat.lock is not None:
            raise ValueError("blocked_no_candidate requires a reason and no candidate or lock")
    elif beat.blocked_reason is None or beat.lock is None:
        raise ValueError("blocked_missing requires a deterministic reason and retained lock")


def _validate_candidate_report(report: Any) -> None:
    ids = [beat.beat_id for beat in report.beats]
    sequences = [beat.sequence for beat in report.beats]
    if len(ids) != len(set(ids)):
        raise ValueError("Candidate Report beat IDs must be unique")
    if sequences != list(range(1, len(report.beats) + 1)):
        raise ValueError("Candidate Report beat sequences must be contiguous and ordered")
    expected = {
        "total_beats": len(report.beats),
        "review_required": sum(beat.state == "review_required" for beat in report.beats),
        "locked_accepted": sum(beat.state == "locked_accepted" for beat in report.beats),
        "blocked_no_candidate": sum(beat.state == "blocked_no_candidate" for beat in report.beats),
        "blocked_missing": sum(beat.state == "blocked_missing" for beat in report.beats),
    }
    if report.summary.model_dump() != expected:
        raise ValueError("Candidate Report summary does not match beat states")


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_request_bytes(request: VisualRequest) -> bytes:
    return canonical_json(request.model_dump(mode="json"))


def compatibility_fingerprint(beat: VisualBeat) -> str:
    def normalized_set(values: tuple[str, ...]) -> list[str]:
        return sorted(set(values), key=lambda item: (item.casefold(), item))

    desired = beat.desired_visual.model_dump(mode="json")
    desired["subjects"] = normalized_set(beat.desired_visual.subjects)
    projection = {
        "desired_visual": desired,
        "media_preference": beat.media_preference,
        "must_have": normalized_set(beat.must_have),
        "preferred": normalized_set(beat.preferred),
        "avoid": normalized_set(beat.avoid),
        "technical_constraints": beat.technical_constraints.model_dump(mode="json"),
        "prior_usage_policy": beat.prior_usage_policy,
        "repeat_within_story": beat.repeat_within_story,
    }
    return sha256_bytes(canonical_json(projection))


def schema_documents() -> dict[str, dict[str, Any]]:
    return {
        "visual-request.v1.schema.json": VisualRequest.model_json_schema(),
        "candidate-report.v1.schema.json": CandidateReport.model_json_schema(),
        "visual-review-template.v1.schema.json": VisualReviewTemplate.model_json_schema(),
        "visual-review.v1.schema.json": VisualReviewDocument.model_json_schema(),
        "candidate-report.v2.schema.json": CandidateReportV2.model_json_schema(),
        "visual-review-template.v2.schema.json": VisualReviewTemplateV2.model_json_schema(),
        "visual-review.v2.schema.json": VisualReviewDocumentV2.model_json_schema(),
    }


def validate_visual_review_document(value: Any) -> VisualReviewDocument | VisualReviewDocumentV2:
    version = value.get("contract_version") if isinstance(value, dict) else None
    if version == 1:
        return VisualReviewDocument.model_validate(value)
    if version == 2:
        return VisualReviewDocumentV2.model_validate(value)
    raise ValueError(f"Unsupported Visual Review contract_version: {version}")


def validate_template_entry(value: Any) -> CandidateReviewTemplateEntry | BlockedGuidanceTemplateEntry:
    return TypeAdapter(TemplateEntry).validate_python(value)
