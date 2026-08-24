from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import (
    AssetReviewAnnotation,
    BeatAssetRejection,
    BeatCandidate,
    BeatSelection,
    CandidatePackage,
    MediaAsset,
    VisualBeat as VisualBeatRow,
    VisualBeatRevision,
    VisualRequestRevision,
    VisualReview,
    VisualReviewEntry,
    VisualReviewTemplate as VisualReviewTemplateRow,
    VisualWorkflow,
)
from ..services import MediaCatalogService, SearchMediaRequest
from ..services.schemas import AssetDetailResult, SearchCandidateResult
from .artifacts import extract_video_frames, file_sha256, render_storyboard, write_json
from .contracts import (
    CandidateReport,
    CompletedBlockedGuidanceEntry,
    CompletedCandidateReviewEntry,
    ReplacementGuidance,
    SearchDirective,
    VisualBeat,
    VisualRequest,
    VisualReviewDocument,
    VisualReviewTemplate,
    canonical_request_bytes,
    compatibility_fingerprint,
    sha256_bytes,
)


class VisualWorkflowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ImportResult:
    workflow_id: str
    request_id: str
    request_revision: int
    story_id: str
    beats: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "request_id": self.request_id,
            "request_revision": self.request_revision,
            "story_id": self.story_id,
            "beats": self.beats,
        }


@dataclass(frozen=True, slots=True)
class PackageResult:
    workflow_id: str
    package_id: str
    review_id: str
    iteration: int
    candidate_report_path: str
    storyboard_path: str
    review_template_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "package_id": self.package_id,
            "review_id": self.review_id,
            "iteration": self.iteration,
            "candidate_report_path": self.candidate_report_path,
            "storyboard_path": self.storyboard_path,
            "review_template_path": self.review_template_path,
        }


@dataclass(frozen=True, slots=True)
class ReviewImportResult:
    workflow_id: str
    review_id: str
    iteration: int
    accepted: int
    replaced: int
    guidance: int
    workflow_status: str
    idempotent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "review_id": self.review_id,
            "iteration": self.iteration,
            "accepted": self.accepted,
            "replaced": self.replaced,
            "guidance": self.guidance,
            "workflow_status": self.workflow_status,
            "idempotent": self.idempotent,
        }


class VisualWorkflowService:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self.settings = settings
        self.engine = engine
        self.catalog = MediaCatalogService(engine)

    @staticmethod
    def validate_request_data(value: Any) -> VisualRequest:
        try:
            return VisualRequest.model_validate(value)
        except ValidationError as exc:
            raise VisualWorkflowError(f"Visual Request validation failed: {exc}") from exc

    @classmethod
    def validate_request_file(cls, path: Path) -> VisualRequest:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise VisualWorkflowError(f"Could not read Visual Request: {exc}") from exc
        return cls.validate_request_data(value)

    def start_workflow(self, path: Path) -> ImportResult:
        request = self.validate_request_file(path)
        workflow_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        normalized = request.model_dump(mode="json")
        digest = sha256_bytes(canonical_request_bytes(request))
        with Session(self.engine) as session:
            workflow = VisualWorkflow(
                id=workflow_id,
                story_external_id=request.story.story_id,
                status="active",
            )
            revision = VisualRequestRevision(
                id=request_id,
                workflow_id=workflow_id,
                revision=1,
                document_sha256=digest,
                normalized_json=normalized,
                imported_at=_utcnow(),
            )
            session.add(workflow)
            session.flush()
            session.add(revision)
            session.flush()
            for beat in request.beats:
                row = VisualBeatRow(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    external_beat_id=beat.beat_id,
                    state="pending",
                )
                session.add(row)
                session.flush()
                session.add(_beat_revision(revision.id, row.id, beat))
            session.commit()
        return ImportResult(workflow_id, request_id, 1, request.story.story_id, len(request.beats))

    def revise_workflow(self, workflow_id: str, path: Path) -> ImportResult:
        request = self.validate_request_file(path)
        normalized = request.model_dump(mode="json")
        digest = sha256_bytes(canonical_request_bytes(request))
        request_id = str(uuid.uuid4())
        with Session(self.engine) as session:
            workflow = session.get(VisualWorkflow, workflow_id)
            if workflow is None:
                raise VisualWorkflowError(f"Workflow not found: {workflow_id}")
            if workflow.story_external_id != request.story.story_id:
                raise VisualWorkflowError("Revised request story_id does not match the workflow")
            awaiting = session.scalar(
                select(CandidatePackage).where(
                    CandidatePackage.workflow_id == workflow_id,
                    CandidatePackage.status == "awaiting_review",
                )
            )
            if awaiting is not None:
                raise VisualWorkflowError("Cannot revise a workflow while a package awaits review")
            existing_beats = {
                item.external_beat_id: item
                for item in session.scalars(
                    select(VisualBeatRow).where(VisualBeatRow.workflow_id == workflow_id)
                )
            }
            incoming_ids = {beat.beat_id for beat in request.beats}
            missing = sorted(set(existing_beats) - incoming_ids)
            if missing:
                raise VisualWorkflowError(
                    "Request revisions cannot omit existing beats: " + ", ".join(missing)
                )
            for beat in request.beats:
                row = existing_beats.get(beat.beat_id)
                if row is None:
                    continue
                selection = session.scalar(
                    select(BeatSelection).where(
                        BeatSelection.workflow_id == workflow_id,
                        BeatSelection.beat_id == row.id,
                    )
                )
                fingerprint = compatibility_fingerprint(beat)
                if selection and selection.lock_compatibility_sha256 != fingerprint:
                    raise VisualWorkflowError(
                        f"Locked beat {beat.beat_id} is incompatible with the revised request; "
                        "assign a new beat_id or use a future administrative operation"
                    )
            next_revision = (
                session.scalar(
                    select(func.max(VisualRequestRevision.revision)).where(
                        VisualRequestRevision.workflow_id == workflow_id
                    )
                )
                or 0
            ) + 1
            revision = VisualRequestRevision(
                id=request_id,
                workflow_id=workflow_id,
                revision=next_revision,
                document_sha256=digest,
                normalized_json=normalized,
                imported_at=_utcnow(),
            )
            session.add(revision)
            session.flush()
            for beat in request.beats:
                row = existing_beats.get(beat.beat_id)
                if row is None:
                    row = VisualBeatRow(
                        id=str(uuid.uuid4()),
                        workflow_id=workflow_id,
                        external_beat_id=beat.beat_id,
                        state="pending",
                    )
                    session.add(row)
                    session.flush()
                session.add(_beat_revision(revision.id, row.id, beat))
            workflow.status = "active"
            session.commit()
        return ImportResult(workflow_id, request_id, next_revision, request.story.story_id, len(request.beats))

    def generate_package(self, workflow_id: str) -> PackageResult:
        package_id = str(uuid.uuid4())
        review_id = str(uuid.uuid4())
        with Session(self.engine) as session:
            workflow = session.get(VisualWorkflow, workflow_id)
            if workflow is None:
                raise VisualWorkflowError(f"Workflow not found: {workflow_id}")
            awaiting = session.scalar(
                select(CandidatePackage).where(
                    CandidatePackage.workflow_id == workflow_id,
                    CandidatePackage.status == "awaiting_review",
                )
            )
            if awaiting is not None:
                raise VisualWorkflowError(
                    f"Package {awaiting.id} already awaits review for this workflow"
                )
            revision = session.scalar(
                select(VisualRequestRevision)
                .where(VisualRequestRevision.workflow_id == workflow_id)
                .order_by(VisualRequestRevision.revision.desc())
            )
            if revision is None:
                raise VisualWorkflowError("Workflow has no Visual Request revision")
            request = VisualRequest.model_validate(revision.normalized_json)
            iteration = (
                session.scalar(
                    select(func.max(CandidatePackage.iteration)).where(
                        CandidatePackage.workflow_id == workflow_id
                    )
                )
                or 0
            ) + 1
            package = CandidatePackage(
                id=package_id,
                workflow_id=workflow_id,
                request_revision_id=revision.id,
                iteration=iteration,
                status="building",
                review_id=review_id,
            )
            request_revision_id_value = revision.id
            session.add(package)
            session.commit()

        artifact_dir = self._artifact_dir(request.story.story_id, workflow_id, iteration)
        report_path = artifact_dir / "candidate-report.json"
        storyboard_path = artifact_dir / "storyboard.pdf"
        template_path = artifact_dir / "review-template.json"
        report_relative = _relative_to_root(report_path, self.settings.root)
        storyboard_relative = _relative_to_root(storyboard_path, self.settings.root)
        template_relative = _relative_to_root(template_path, self.settings.root)
        generated_at = _utcnow()

        try:
            with Session(self.engine) as session:
                revision = session.get(VisualRequestRevision, request_revision_id_value)
                assert revision is not None
                request = VisualRequest.model_validate(revision.normalized_json)
                request_id_value = revision.id
                request_revision_value = revision.revision
                request_document_sha256 = revision.document_sha256
                beat_rows = {
                    item.external_beat_id: item
                    for item in session.scalars(
                        select(VisualBeatRow).where(VisualBeatRow.workflow_id == workflow_id)
                    )
                }
                reserved_ids, reserved_hashes = self._locked_reservations(session, workflow_id)
                report_beats: list[dict[str, Any]] = []
                for beat in request.beats:
                    row = beat_rows[beat.beat_id]
                    effective = self._effective_beat(session, row.id, beat)
                    snapshot = _request_snapshot(effective)
                    selection = session.scalar(
                        select(BeatSelection).where(
                            BeatSelection.workflow_id == workflow_id,
                            BeatSelection.beat_id == row.id,
                        )
                    )
                    if selection is not None:
                        report_beats.append(
                            self._locked_report_beat(session, row, effective, selection)
                        )
                        continue
                    row.state = "sourcing"
                    chosen, blocked = self._source_beat(
                        session,
                        workflow_id,
                        row,
                        effective,
                        package_id,
                        artifact_dir,
                        reserved_ids,
                        reserved_hashes,
                    )
                    if chosen is None:
                        row.state = "blocked_no_candidate"
                        report_beats.append(
                            {
                                "beat_id": beat.beat_id,
                                "sequence": beat.sequence,
                                "state": "blocked_no_candidate",
                                "request_snapshot": snapshot,
                                "candidates": [],
                                "blocked_reason": blocked,
                                "lock": None,
                            }
                        )
                    else:
                        row.state = "review_required"
                        report_beats.append(
                            {
                                "beat_id": beat.beat_id,
                                "sequence": beat.sequence,
                                "state": "review_required",
                                "request_snapshot": snapshot,
                                "candidates": [chosen],
                                "blocked_reason": None,
                                "lock": None,
                            }
                        )
                        if not effective.repeat_within_story:
                            reserved_ids.add(chosen["asset_id"])
                            reserved_hashes.add(chosen["asset_sha256"])
                session.commit()

            summary = {
                "total_beats": len(report_beats),
                "review_required": sum(item["state"] == "review_required" for item in report_beats),
                "locked_accepted": sum(item["state"] == "locked_accepted" for item in report_beats),
                "blocked_no_candidate": sum(item["state"] == "blocked_no_candidate" for item in report_beats),
                "blocked_missing": sum(item["state"] == "blocked_missing" for item in report_beats),
            }
            report_model = CandidateReport.model_validate(
                {
                    "document_type": "candidate_report",
                    "contract_version": 1,
                    "workflow_id": workflow_id,
                    "request_id": request_id_value,
                    "request_revision": request_revision_value,
                    "request_document_sha256": request_document_sha256,
                    "package_id": package_id,
                    "review_id": review_id,
                    "iteration": iteration,
                    "generated_at": generated_at.isoformat(),
                    "story": {"story_id": request.story.story_id, "title": request.story.title},
                    "review_threshold": 90,
                    "expected_storyboard": {"relative_path": storyboard_relative},
                    "expected_review_template": {"relative_path": template_relative},
                    "summary": summary,
                    "beats": report_beats,
                }
            )
            report_json = report_model.model_dump(mode="json")
            report_hash = write_json(report_path, report_json)
            page_count = render_storyboard(report_json, storyboard_path, root=self.settings.root)
            storyboard_hash = file_sha256(storyboard_path)
            template_model = self._review_template(
                report_model,
                candidate_report_sha256=report_hash,
                storyboard_pdf_sha256=storyboard_hash,
            )
            template_json = template_model.model_dump(mode="json")
            template_hash = write_json(template_path, template_json)
            with Session(self.engine) as session:
                package = session.get(CandidatePackage, package_id)
                assert package is not None
                package.candidate_report_path = report_relative
                package.candidate_report_sha256 = report_hash
                package.storyboard_path = storyboard_relative
                package.storyboard_sha256 = storyboard_hash
                package.review_template_path = template_relative
                package.review_template_sha256 = template_hash
                package.generated_at = generated_at
                package.status = "awaiting_review"
                session.add(
                    VisualReviewTemplateRow(
                        review_id=review_id,
                        package_id=package_id,
                        template_json=template_json,
                        template_sha256=template_hash,
                    )
                )
                session.commit()
            return PackageResult(
                workflow_id,
                package_id,
                review_id,
                iteration,
                report_relative,
                storyboard_relative,
                template_relative,
            )
        except Exception:
            with Session(self.engine) as session:
                failed = session.get(CandidatePackage, package_id)
                if failed is not None:
                    failed.status = "generation_failed"
                    session.commit()
            raise

    def import_review(self, workflow_id: str, path: Path) -> ReviewImportResult:
        try:
            raw_bytes = path.read_bytes()
            raw_value = json.loads(raw_bytes.decode("utf-8"))
            review = VisualReviewDocument.model_validate(raw_value)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
            raise VisualWorkflowError(f"Visual Review validation failed: {exc}") from exc
        digest = sha256_bytes(raw_bytes)
        review_id = review.bookkeeping.review_id
        with Session(self.engine) as session:
            template = session.get(VisualReviewTemplateRow, review_id)
            if template is None:
                raise VisualWorkflowError(f"Review Template not found: {review_id}")
            package = session.get(CandidatePackage, template.package_id)
            assert package is not None
            if package.workflow_id != workflow_id:
                raise VisualWorkflowError("Review does not belong to the requested workflow")
            existing = session.get(VisualReview, review_id)
            if existing is not None:
                if existing.completed_document_sha256 != digest:
                    raise VisualWorkflowError("Review ID was already imported with different content")
                workflow = session.get(VisualWorkflow, workflow_id)
                assert workflow is not None
                return ReviewImportResult(
                    workflow_id, review_id, package.iteration, 0, 0, 0, workflow.status, True
                )
            if package.status != "awaiting_review":
                raise VisualWorkflowError("Candidate package is not awaiting review")
            self._validate_review_integrity(review, template.template_json, package)
            completed = VisualReview(
                review_id=review_id,
                completed_document_sha256=digest,
                completed_json=review.model_dump(mode="json"),
                imported_at=_utcnow(),
            )
            session.add(completed)
            session.flush()
            beat_rows = {
                item.external_beat_id: item
                for item in session.scalars(
                    select(VisualBeatRow).where(VisualBeatRow.workflow_id == workflow_id)
                )
            }
            accepted = replaced = guidance_count = 0
            for entry in review.review_entries:
                beat = beat_rows[entry.beat_id]
                if isinstance(entry, CompletedCandidateReviewEntry):
                    candidate = session.get(BeatCandidate, entry.candidate.candidate_id)
                    if candidate is None or candidate.beat_id != beat.id:
                        raise VisualWorkflowError(f"Candidate mismatch for beat {entry.beat_id}")
                    editorial = entry.editorial_review
                    review_entry = VisualReviewEntry(
                        review_id=review_id,
                        beat_id=beat.id,
                        entry_type="candidate_review",
                        candidate_id=candidate.id,
                        alignment_score=editorial.alignment_score,
                        decision=editorial.decision,
                        mismatch_json={
                            "reasons": [item.model_dump(mode="json") for item in editorial.mismatch_reasons],
                            "explanation": editorial.mismatch_explanation,
                        },
                        replacement_guidance_json=(
                            editorial.replacement_guidance.model_dump(mode="json")
                            if editorial.replacement_guidance
                            else None
                        ),
                        catalog_annotations_json=(
                            editorial.catalog_annotations.model_dump(mode="json")
                            if editorial.catalog_annotations
                            else None
                        ),
                    )
                    session.add(review_entry)
                    if editorial.decision == "accept":
                        accepted += 1
                        candidate.status = "accepted"
                        beat.state = "accepted_locked"
                        beat_revision = session.scalar(
                            select(VisualBeatRevision).where(
                                VisualBeatRevision.request_revision_id == package.request_revision_id,
                                VisualBeatRevision.beat_id == beat.id,
                            )
                        )
                        assert beat_revision is not None
                        session.add(
                            BeatSelection(
                                workflow_id=workflow_id,
                                beat_id=beat.id,
                                candidate_id=candidate.id,
                                asset_id=candidate.asset_id,
                                asset_sha256=candidate.asset_sha256,
                                review_id=review_id,
                                alignment_score=editorial.alignment_score,
                                lock_compatibility_sha256=beat_revision.lock_compatibility_sha256,
                                status="locked",
                            )
                        )
                        if editorial.catalog_annotations is not None:
                            session.add(
                                AssetReviewAnnotation(
                                    asset_id=candidate.asset_id,
                                    review_id=review_id,
                                    source_type="chatgpt_visual_review",
                                    annotations_json=editorial.catalog_annotations.model_dump(mode="json"),
                                )
                            )
                    else:
                        replaced += 1
                        candidate.status = "rejected"
                        beat.state = "rejected"
                        session.add(
                            BeatAssetRejection(
                                workflow_id=workflow_id,
                                beat_id=beat.id,
                                candidate_id=candidate.id,
                                asset_id=candidate.asset_id,
                                asset_sha256=candidate.asset_sha256,
                                review_id=review_id,
                            )
                        )
                elif isinstance(entry, CompletedBlockedGuidanceEntry):
                    guidance_count += 1
                    beat.state = "rejected"
                    session.add(
                        VisualReviewEntry(
                            review_id=review_id,
                            beat_id=beat.id,
                            entry_type="blocked_beat_guidance",
                            action="revise_search",
                            replacement_guidance_json=entry.editorial_guidance.replacement_guidance.model_dump(mode="json"),
                        )
                    )
            package.status = "reviewed"
            workflow = session.get(VisualWorkflow, workflow_id)
            assert workflow is not None
            unresolved = session.scalar(
                select(func.count()).select_from(VisualBeatRow).where(
                    VisualBeatRow.workflow_id == workflow_id,
                    VisualBeatRow.state != "accepted_locked",
                )
            ) or 0
            workflow.status = "complete" if unresolved == 0 else "active"
            session.commit()
            return ReviewImportResult(
                workflow_id,
                review_id,
                package.iteration,
                accepted,
                replaced,
                guidance_count,
                workflow.status,
            )

    def get_status(self, workflow_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            workflow = session.get(VisualWorkflow, workflow_id)
            if workflow is None:
                raise VisualWorkflowError(f"Workflow not found: {workflow_id}")
            revisions = session.scalar(
                select(func.count()).select_from(VisualRequestRevision).where(
                    VisualRequestRevision.workflow_id == workflow_id
                )
            ) or 0
            states = dict(
                session.execute(
                    select(VisualBeatRow.state, func.count(VisualBeatRow.id))
                    .where(VisualBeatRow.workflow_id == workflow_id)
                    .group_by(VisualBeatRow.state)
                ).all()
            )
            latest_package = session.scalar(
                select(CandidatePackage)
                .where(CandidatePackage.workflow_id == workflow_id)
                .order_by(CandidatePackage.iteration.desc())
            )
            return {
                "workflow_id": workflow.id,
                "story_id": workflow.story_external_id,
                "status": workflow.status,
                "request_revisions": revisions,
                "beat_states": states,
                "latest_package": (
                    {
                        "package_id": latest_package.id,
                        "iteration": latest_package.iteration,
                        "status": latest_package.status,
                    }
                    if latest_package
                    else None
                ),
            }

    def get_artifacts(self, workflow_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            if session.get(VisualWorkflow, workflow_id) is None:
                raise VisualWorkflowError(f"Workflow not found: {workflow_id}")
            packages = session.scalars(
                select(CandidatePackage)
                .where(CandidatePackage.workflow_id == workflow_id)
                .order_by(CandidatePackage.iteration)
            )
            return [
                {
                    "package_id": item.id,
                    "iteration": item.iteration,
                    "status": item.status,
                    "candidate_report_path": item.candidate_report_path,
                    "storyboard_path": item.storyboard_path,
                    "review_template_path": item.review_template_path,
                }
                for item in packages
            ]

    def _source_beat(
        self,
        session: Session,
        workflow_id: str,
        beat_row: VisualBeatRow,
        beat: VisualBeat,
        package_id: str,
        artifact_dir: Path,
        reserved_ids: set[int],
        reserved_hashes: set[str],
    ) -> tuple[dict[str, Any] | None, dict[str, str]]:
        rejected = list(
            session.scalars(
                select(BeatAssetRejection).where(
                    BeatAssetRejection.workflow_id == workflow_id,
                    BeatAssetRejection.beat_id == beat_row.id,
                )
            )
        )
        rejected_ids = {item.asset_id for item in rejected}
        rejected_hashes = {item.asset_sha256 for item in rejected}
        saw_catalog = False
        saw_eligible = False
        saw_excluded = False
        choices: list[tuple[int, int, SearchCandidateResult, AssetDetailResult, SearchDirective]] = []
        for directive_index, directive in enumerate(beat.search_directives):
            media_type = _effective_media_type(beat.media_preference, directive.media_type)
            if media_type is False:
                continue
            filters = _combined_filters(beat, directive)
            if filters is None:
                continue
            query = " ".join((directive.query, *directive.required_terms)).strip()
            result = self.catalog.search_media(
                SearchMediaRequest(
                    query=query,
                    media_type=media_type,
                    orientation=filters["orientation"],
                    min_width=filters["minimum_width"],
                    min_height=filters["minimum_height"],
                    min_duration_ms=filters["minimum_duration_ms"],
                    max_duration_ms=filters["maximum_duration_ms"],
                    usage="unused" if beat.prior_usage_policy == "forbid_prior_usage" else None,
                    availability="available",
                    limit=500,
                )
            )
            for item in result.candidates:
                saw_catalog = True
                detail = self.catalog.get_asset_detail(item.asset_id)
                if _contains_excluded(detail, directive.excluded_terms):
                    saw_excluded = True
                    continue
                if item.asset_id in rejected_ids or (item.sha256 and item.sha256 in rejected_hashes):
                    saw_excluded = True
                    continue
                if not beat.repeat_within_story and (
                    item.asset_id in reserved_ids or (item.sha256 and item.sha256 in reserved_hashes)
                ):
                    saw_excluded = True
                    continue
                license_status = _license_status(detail)
                if license_status == "restricted":
                    continue
                if not item.sha256 or item.width is None or item.height is None or item.file_size_bytes is None:
                    continue
                if item.media_type == "video" and item.duration_ms is None:
                    continue
                saw_eligible = True
                score = _retrieval_score(item, beat.prior_usage_policy)
                choices.append((score, -directive_index, item, detail, directive))
        choices.sort(key=lambda entry: (-entry[0], -entry[1], entry[2].rank, entry[2].asset_id))
        preview_failed = False
        for score, _directive_order, item, detail, directive in choices:
            try:
                preview = self._preview_for_candidate(
                    item,
                    artifact_dir / "previews" / beat.beat_id / str(item.asset_id),
                )
            except (OSError, RuntimeError):
                preview_failed = True
                continue
            candidate_id = str(uuid.uuid4())
            report_candidate = _report_candidate(
                candidate_id, item, detail, directive, score, preview
            )
            session.add(
                BeatCandidate(
                    id=candidate_id,
                    package_id=package_id,
                    beat_id=beat_row.id,
                    asset_id=item.asset_id,
                    asset_sha256=item.sha256,
                    status="proposed",
                    retrieval_json=report_candidate["retrieval"],
                    preview_json=preview,
                )
            )
            session.flush()
            return report_candidate, {}
        if preview_failed and saw_eligible:
            return None, {
                "code": "preview_generation_failed",
                "explanation": "Eligible local media existed but no reliable review preview could be generated.",
            }
        if saw_excluded and saw_catalog:
            return None, {
                "code": "all_matches_excluded",
                "explanation": "Local matches were excluded by rejection history, reservations, or explicit filters.",
            }
        if saw_catalog:
            return None, {
                "code": "no_technically_eligible_matches",
                "explanation": "Local matches existed, but none met the structured technical and licensing requirements.",
            }
        return None, {
            "code": "no_local_matches",
            "explanation": "The explicit local search directives returned no catalog matches.",
        }

    def _preview_for_candidate(
        self, candidate: SearchCandidateResult, preview_dir: Path
    ) -> dict[str, Any]:
        if candidate.current_location is None:
            raise RuntimeError("candidate is not locally available")
        source = _resolve_relative(self.settings.root, candidate.current_location)
        if candidate.media_type == "image":
            return {"poster_frame_path": candidate.current_location, "video_frames": []}
        if candidate.duration_ms is None:
            raise RuntimeError("video duration is unavailable")
        frames = extract_video_frames(
            source,
            preview_dir,
            duration_ms=candidate.duration_ms,
            root=self.settings.root,
        )
        poster = min(frames, key=lambda item: abs(item["timestamp_ms"] - candidate.duration_ms / 2))
        return {"poster_frame_path": poster["relative_path"], "video_frames": frames}

    def _effective_beat(
        self, session: Session, beat_row_id: str, original: VisualBeat
    ) -> VisualBeat:
        latest = session.scalar(
            select(VisualReviewEntry)
            .where(
                VisualReviewEntry.beat_id == beat_row_id,
                VisualReviewEntry.replacement_guidance_json.is_not(None),
            )
            .order_by(VisualReviewEntry.id.desc())
        )
        if latest is None or latest.replacement_guidance_json is None:
            return original
        guidance = ReplacementGuidance.model_validate(latest.replacement_guidance_json)
        update: dict[str, Any] = {
            "search_directives": guidance.revised_search_directives,
            "must_have": guidance.must_have,
            "preferred": guidance.preferred,
            "avoid": guidance.avoid,
        }
        if guidance.media_preference_change is not None:
            update["media_preference"] = guidance.media_preference_change
        return original.model_copy(update=update)

    @staticmethod
    def _locked_reservations(
        session: Session, workflow_id: str
    ) -> tuple[set[int], set[str]]:
        selections = list(
            session.scalars(
                select(BeatSelection).where(
                    BeatSelection.workflow_id == workflow_id,
                    BeatSelection.status == "locked",
                )
            )
        )
        return {item.asset_id for item in selections}, {item.asset_sha256 for item in selections}

    def _locked_report_beat(
        self,
        session: Session,
        beat_row: VisualBeatRow,
        beat: VisualBeat,
        selection: BeatSelection,
    ) -> dict[str, Any]:
        blocked: dict[str, str] | None = None
        try:
            detail = self.catalog.get_asset_detail(selection.asset_id)
        except Exception:
            detail = None
            blocked = {
                "code": "catalog_identity_mismatch",
                "explanation": "The locked catalog asset no longer exists.",
            }
        if detail is not None and not detail.available:
            blocked = {
                "code": "file_unavailable",
                "explanation": "The accepted locked asset is no longer locally available.",
            }
        elif detail is not None and detail.sha256 != selection.asset_sha256:
            blocked = {
                "code": "asset_hash_mismatch",
                "explanation": "The accepted locked asset no longer matches its recorded SHA-256.",
            }
        candidate = session.get(BeatCandidate, selection.candidate_id)
        if blocked is not None:
            selection.status = "blocked_missing"
            selection.blocked_reason = blocked["code"]
            beat_row.state = "blocked_missing"
            candidates = []
            preview_exists = False
            if candidate is not None:
                poster = candidate.preview_json.get("poster_frame_path")
                if isinstance(poster, str):
                    preview_exists = _resolve_relative(self.settings.root, poster).is_file()
            if candidate is not None and detail is not None and preview_exists:
                candidates = [
                    _report_candidate_from_lock(candidate, detail, available=False)
                ]
            return {
                "beat_id": beat.beat_id,
                "sequence": beat.sequence,
                "state": "blocked_missing",
                "request_snapshot": _request_snapshot(beat),
                "candidates": candidates,
                "blocked_reason": blocked,
                "lock": _report_lock(selection),
            }
        assert detail is not None and candidate is not None
        beat_row.state = "accepted_locked"
        return {
            "beat_id": beat.beat_id,
            "sequence": beat.sequence,
            "state": "locked_accepted",
            "request_snapshot": _request_snapshot(beat),
            "candidates": [_report_candidate_from_lock(candidate, detail, available=True)],
            "blocked_reason": None,
            "lock": _report_lock(selection),
        }

    @staticmethod
    def _review_template(
        report: CandidateReport,
        *,
        candidate_report_sha256: str,
        storyboard_pdf_sha256: str,
    ) -> VisualReviewTemplate:
        entries: list[dict[str, Any]] = []
        for beat in report.beats:
            if beat.state == "review_required":
                candidate = beat.candidates[0]
                entries.append(
                    {
                        "entry_type": "candidate_review",
                        "beat_id": beat.beat_id,
                        "sequence": beat.sequence,
                        "candidate": {
                            "candidate_id": candidate.candidate_id,
                            "asset_id": candidate.asset_id,
                            "asset_sha256": candidate.asset_sha256,
                        },
                        "editorial_review": {
                            "alignment_score": None,
                            "decision": None,
                            "mismatch_reasons": [],
                            "mismatch_explanation": None,
                            "replacement_guidance": None,
                            "catalog_annotations": None,
                        },
                    }
                )
            elif beat.state == "blocked_no_candidate":
                assert beat.blocked_reason is not None
                entries.append(
                    {
                        "entry_type": "blocked_beat_guidance",
                        "beat_id": beat.beat_id,
                        "sequence": beat.sequence,
                        "blocked_reason": {
                            "code": beat.blocked_reason.code,
                            "explanation": beat.blocked_reason.explanation,
                        },
                        "editorial_guidance": {
                            "action": None,
                            "replacement_guidance": None,
                        },
                    }
                )
        return VisualReviewTemplate.model_validate(
            {
                "document_type": "visual_review",
                "contract_version": 1,
                "bookkeeping": {
                    "workflow_id": report.workflow_id,
                    "request_id": report.request_id,
                    "request_revision": report.request_revision,
                    "request_document_sha256": report.request_document_sha256,
                    "package_id": report.package_id,
                    "candidate_report_sha256": candidate_report_sha256,
                    "storyboard_pdf_sha256": storyboard_pdf_sha256,
                    "review_id": report.review_id,
                    "iteration": report.iteration,
                },
                "story": {"story_id": report.story.story_id},
                "review_entries": entries,
            }
        )

    def _validate_review_integrity(
        self,
        review: VisualReviewDocument,
        template_json: dict[str, Any],
        package: CandidatePackage,
    ) -> None:
        if review.bookkeeping.model_dump(mode="json") != template_json["bookkeeping"]:
            raise VisualWorkflowError("Review bookkeeping was modified")
        if review.story.model_dump(mode="json") != template_json["story"]:
            raise VisualWorkflowError("Review story identity was modified")
        if package.candidate_report_path is None or package.storyboard_path is None:
            raise VisualWorkflowError("Package artifacts are incomplete")
        report_path = _resolve_relative(self.settings.root, package.candidate_report_path)
        storyboard_path = _resolve_relative(self.settings.root, package.storyboard_path)
        if file_sha256(report_path) != review.bookkeeping.candidate_report_sha256:
            raise VisualWorkflowError("Candidate Report hash no longer matches the Review Template")
        if file_sha256(storyboard_path) != review.bookkeeping.storyboard_pdf_sha256:
            raise VisualWorkflowError("Storyboard PDF hash no longer matches the Review Template")
        expected = template_json["review_entries"]
        actual = [item.model_dump(mode="json") for item in review.review_entries]
        if len(actual) != len(expected):
            raise VisualWorkflowError("Review entries do not match the generated template")
        for completed, blank in zip(actual, expected, strict=True):
            for key, value in blank.items():
                if key in ("editorial_review", "editorial_guidance"):
                    continue
                if completed.get(key) != value:
                    raise VisualWorkflowError(
                        f"Immutable review entry data was modified for beat {blank['beat_id']}"
                    )

    def _artifact_dir(self, story_id: str, workflow_id: str, iteration: int) -> Path:
        path = (
            self.settings.root
            / "Projects"
            / story_id
            / "visuals"
            / workflow_id
            / "iterations"
            / f"{iteration:04d}"
        )
        path.resolve(strict=False).relative_to(self.settings.root.resolve())
        if path.exists() and any(path.iterdir()):
            raise VisualWorkflowError(f"Artifact directory already exists and is not empty: {path}")
        return path


def _beat_revision(request_revision_id: str, beat_id: str, beat: VisualBeat) -> VisualBeatRevision:
    return VisualBeatRevision(
        request_revision_id=request_revision_id,
        beat_id=beat_id,
        sequence=beat.sequence,
        specification_json=beat.model_dump(mode="json"),
        lock_compatibility_sha256=compatibility_fingerprint(beat),
    )


def _request_snapshot(beat: VisualBeat) -> dict[str, Any]:
    return beat.model_dump(
        mode="json",
        exclude={"beat_id", "sequence"},
    )


def _effective_media_type(
    preference: str, directive_type: str
) -> str | None | Literal[False]:
    if preference == "either" and directive_type == "either":
        return None
    if preference == "either":
        return directive_type
    if directive_type == "either":
        return preference
    return preference if preference == directive_type else False


def _combined_filters(beat: VisualBeat, directive: SearchDirective) -> dict[str, Any] | None:
    technical = beat.technical_constraints
    directive_filters = directive.filters
    orientation = directive_filters.orientation
    if technical.orientation != "any":
        if orientation and orientation != technical.orientation:
            return None
        orientation = technical.orientation
    duration = technical.video_duration_ms
    minimum_duration = max(
        [value for value in (directive_filters.minimum_duration_ms, duration.minimum if duration else None) if value is not None],
        default=None,
    )
    maximum_values = [
        value for value in (directive_filters.maximum_duration_ms, duration.maximum if duration else None)
        if value is not None
    ]
    maximum_duration = min(maximum_values) if maximum_values else None
    if minimum_duration is not None and maximum_duration is not None and maximum_duration < minimum_duration:
        return None
    return {
        "orientation": orientation,
        "minimum_width": max(
            [value for value in (directive_filters.minimum_width, technical.minimum_width) if value is not None],
            default=None,
        ),
        "minimum_height": max(
            [value for value in (directive_filters.minimum_height, technical.minimum_height) if value is not None],
            default=None,
        ),
        "minimum_duration_ms": minimum_duration,
        "maximum_duration_ms": maximum_duration,
    }


def _contains_excluded(detail: AssetDetailResult, terms: tuple[str, ...]) -> bool:
    if not terms:
        return False
    text = " ".join(
        [
            detail.relative_path,
            detail.title or "",
            detail.description or "",
            *detail.tags,
            *(source.provider or "" for source in detail.sources),
            *(source.creator_name or "" for source in detail.sources),
        ]
    ).casefold()
    return any(term.casefold() in text for term in terms)


def _license_status(detail: AssetDetailResult) -> str:
    license_record = detail.license
    if license_record is None:
        return "unknown"
    if license_record.commercial_use_allowed is False or license_record.modifications_allowed is False:
        return "restricted"
    if license_record.commercial_use_allowed is True and license_record.modifications_allowed is True:
        return "known"
    return "unknown"


def _retrieval_score(candidate: SearchCandidateResult, prior_policy: str) -> int:
    if prior_policy != "allow_prior_usage":
        return candidate.score
    deductions = 0
    for reason in candidate.score_reasons:
        if reason.startswith(("low_total_usage:+", "low_recent_usage:+")):
            deductions += int(reason.rsplit("+", 1)[1])
    return candidate.score - deductions


def _report_candidate(
    candidate_id: str,
    candidate: SearchCandidateResult,
    detail: AssetDetailResult,
    directive: SearchDirective,
    retrieval_score: int,
    preview: dict[str, Any],
) -> dict[str, Any]:
    location = next(
        (item for item in detail.locations if item.relative_path == detail.current_location),
        detail.locations[0] if detail.locations else None,
    )
    source = detail.sources[0] if detail.sources else None
    license_record = detail.license
    return {
        "candidate_id": candidate_id,
        "asset_id": candidate.asset_id,
        "asset_sha256": candidate.sha256,
        "media_type": candidate.media_type,
        "catalog_status": (
            "previously_downloaded"
            if location and location.provenance_type == "provider_download"
            else "existing_local"
        ),
        "relative_path": candidate.current_location or candidate.relative_path,
        "available": True,
        "technical": {
            "mime_type": candidate.mime_type,
            "width": candidate.width,
            "height": candidate.height,
            "duration_ms": candidate.duration_ms,
            "file_size_bytes": candidate.file_size_bytes,
        },
        "provenance": {
            "origin": location.provenance_type if location else "local_import",
            "provider": source.provider if source else None,
            "provider_asset_id": source.provider_asset_id if source else None,
            "source_url": source.source_url if source else None,
            "creator_name": source.creator_name if source else None,
            "creator_url": source.creator_url if source else None,
        },
        "license": {
            "status": _license_status(detail),
            "license_name": license_record.license_name if license_record else None,
            "license_url": license_record.license_url if license_record else None,
            "attribution_required": license_record.attribution_required if license_record else None,
            "attribution_text": license_record.attribution_text if license_record else None,
            "commercial_use_allowed": license_record.commercial_use_allowed if license_record else None,
            "modifications_allowed": license_record.modifications_allowed if license_record else None,
        },
        "usage": {
            "usage_count": detail.usage_count,
            "last_used_at": detail.last_used_at.isoformat() if detail.last_used_at else None,
            "recent_usage_references": [
                item.usage_reference for item in detail.recent_usage if item.usage_reference
            ],
        },
        "retrieval": {
            "stage": "local",
            "query": directive.query,
            "rank": candidate.rank,
            "retrieval_score": retrieval_score,
            "score_reasons": list(candidate.score_reasons),
        },
        "storyboard_visuals": preview,
    }


def _report_candidate_from_lock(
    candidate: BeatCandidate, detail: AssetDetailResult, *, available: bool
) -> dict[str, Any]:
    search_candidate = SearchCandidateResult(
        rank=int(candidate.retrieval_json.get("rank", 1)),
        score=int(candidate.retrieval_json.get("retrieval_score", 0)),
        score_reasons=tuple(candidate.retrieval_json.get("score_reasons", [])),
        asset_id=detail.asset_id,
        relative_path=detail.relative_path,
        current_location=detail.current_location,
        media_type=detail.media_type,
        mime_type=detail.mime_type,
        extension=detail.extension,
        width=detail.width,
        height=detail.height,
        orientation=detail.orientation,
        duration_ms=detail.duration_ms,
        file_size_bytes=detail.file_size_bytes,
        sha256=detail.sha256,
        available=available,
        locations=tuple(item.relative_path for item in detail.locations),
        providers=tuple(item.provider for item in detail.sources if item.provider),
        creators=tuple(item.creator_name for item in detail.sources if item.creator_name),
        tags=detail.tags,
        usage_count=detail.usage_count,
        recent_usage_count=len(detail.recent_usage),
        last_used_at=detail.last_used_at,
    )
    directive = SearchDirective(
        query=str(candidate.retrieval_json.get("query", "locked selection")),
        media_type=detail.media_type,
        required_terms=(),
        excluded_terms=(),
    )
    value = _report_candidate(
        candidate.id,
        search_candidate,
        detail,
        directive,
        int(candidate.retrieval_json.get("retrieval_score", 0)),
        candidate.preview_json,
    )
    value["available"] = available
    value["retrieval"] = candidate.retrieval_json
    return value


def _report_lock(selection: BeatSelection) -> dict[str, Any]:
    return {
        "review_id": selection.review_id,
        "candidate_id": selection.candidate_id,
        "asset_id": selection.asset_id,
        "asset_sha256": selection.asset_sha256,
        "alignment_score": selection.alignment_score,
        "locked_at": selection.locked_at.isoformat(),
    }


def _resolve_relative(root: Path, relative_path: str) -> Path:
    pure = Path(relative_path.replace("/", "\\"))
    if pure.is_absolute() or ".." in pure.parts:
        raise VisualWorkflowError(f"Unsafe project-relative path: {relative_path}")
    resolved = (root / pure).resolve(strict=False)
    resolved.relative_to(root.resolve())
    return resolved


def _relative_to_root(path: Path, root: Path) -> str:
    resolved = path.resolve(strict=False)
    resolved.relative_to(root.resolve())
    return resolved.relative_to(root.resolve()).as_posix()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
