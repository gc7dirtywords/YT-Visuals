"""Add deterministic visual request and review workflow.

Revision ID: 0005_visual_workflow
Revises: 0004_usage_context
Create Date: 2026-08-23
"""

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_visual_workflow"
down_revision: str | None = "0004_usage_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "visual_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("story_external_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("status IN ('active', 'complete', 'blocked')", name=op.f("ck_visual_workflows_status")),
        sa.CheckConstraint("length(trim(story_external_id)) > 0", name=op.f("ck_visual_workflows_story_external_id_not_empty")),
    )
    op.create_table(
        "visual_request_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("document_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("revision > 0", name=op.f("ck_visual_request_revisions_revision_positive")),
        sa.CheckConstraint("length(document_sha256) = 64", name=op.f("ck_visual_request_revisions_document_sha256_length")),
        sa.ForeignKeyConstraint(["workflow_id"], ["visual_workflows.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workflow_id", "revision", name="uq_visual_request_revisions_workflow_revision"),
    )
    op.create_index("ix_visual_request_revisions_workflow_revision", "visual_request_revisions", ["workflow_id", "revision"])
    op.create_table(
        "visual_beats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("external_beat_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("state IN ('pending', 'sourcing', 'review_required', 'rejected', 'blocked_no_candidate', 'accepted_locked', 'blocked_missing')", name=op.f("ck_visual_beats_state")),
        sa.ForeignKeyConstraint(["workflow_id"], ["visual_workflows.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("workflow_id", "external_beat_id", name="uq_visual_beats_workflow_external"),
    )
    op.create_index("ix_visual_beats_workflow_state", "visual_beats", ["workflow_id", "state"])
    op.create_table(
        "visual_beat_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_revision_id", sa.String(36), nullable=False),
        sa.Column("beat_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("specification_json", sa.JSON(), nullable=False),
        sa.Column("lock_compatibility_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_visual_beat_revisions_sequence_positive")),
        sa.CheckConstraint("length(lock_compatibility_sha256) = 64", name=op.f("ck_visual_beat_revisions_compatibility_sha256_length")),
        sa.ForeignKeyConstraint(["request_revision_id"], ["visual_request_revisions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["beat_id"], ["visual_beats.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("request_revision_id", "beat_id", name="uq_visual_beat_revisions_request_beat"),
        sa.UniqueConstraint("request_revision_id", "sequence", name="uq_visual_beat_revisions_request_sequence"),
    )
    op.create_table(
        "candidate_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("request_revision_id", sa.String(36), nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="building"),
        sa.Column("candidate_report_path", sa.String(1024)),
        sa.Column("candidate_report_sha256", sa.String(64)),
        sa.Column("storyboard_path", sa.String(1024)),
        sa.Column("storyboard_sha256", sa.String(64)),
        sa.Column("review_template_path", sa.String(1024)),
        sa.Column("review_template_sha256", sa.String(64)),
        sa.Column("review_id", sa.String(36), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("iteration > 0", name=op.f("ck_candidate_packages_iteration_positive")),
        sa.CheckConstraint("status IN ('building', 'awaiting_review', 'reviewed', 'generation_failed')", name=op.f("ck_candidate_packages_status")),
        sa.ForeignKeyConstraint(["workflow_id"], ["visual_workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["request_revision_id"], ["visual_request_revisions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workflow_id", "iteration", name="uq_candidate_packages_workflow_iteration"),
        sa.UniqueConstraint("review_id", name="uq_candidate_packages_review_id"),
    )
    op.create_index("ix_candidate_packages_workflow_status", "candidate_packages", ["workflow_id", "status"])
    op.create_index(
        "uq_candidate_packages_one_awaiting",
        "candidate_packages",
        ["workflow_id"],
        unique=True,
        sqlite_where=sa.text("status = 'awaiting_review'"),
    )
    op.create_table(
        "beat_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("beat_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="proposed"),
        sa.Column("retrieval_json", sa.JSON(), nullable=False),
        sa.Column("preview_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("status IN ('proposed', 'rejected', 'accepted', 'locked_carried')", name=op.f("ck_beat_candidates_status")),
        sa.ForeignKeyConstraint(["package_id"], ["candidate_packages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["beat_id"], ["visual_beats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("package_id", "beat_id", name="uq_beat_candidates_package_beat"),
    )
    op.create_index("ix_beat_candidates_beat_asset", "beat_candidates", ["beat_id", "asset_id"])
    op.create_index("ix_beat_candidates_package_status", "beat_candidates", ["package_id", "status"])
    op.create_table(
        "visual_review_templates",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column("package_id", sa.String(36), nullable=False),
        sa.Column("template_json", sa.JSON(), nullable=False),
        sa.Column("template_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.ForeignKeyConstraint(["package_id"], ["candidate_packages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("package_id", name="uq_visual_review_templates_package"),
    )
    op.create_table(
        "visual_reviews",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column("completed_document_sha256", sa.String(64), nullable=False),
        sa.Column("completed_json", sa.JSON(), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.ForeignKeyConstraint(["review_id"], ["visual_review_templates.review_id"], ondelete="CASCADE"),
    )
    op.create_table(
        "visual_review_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_id", sa.String(36), nullable=False),
        sa.Column("beat_id", sa.String(36), nullable=False),
        sa.Column("entry_type", sa.String(32), nullable=False),
        sa.Column("candidate_id", sa.String(36)),
        sa.Column("alignment_score", sa.Integer()),
        sa.Column("decision", sa.String(16)),
        sa.Column("action", sa.String(32)),
        sa.Column("mismatch_json", sa.JSON()),
        sa.Column("replacement_guidance_json", sa.JSON()),
        sa.Column("catalog_annotations_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("entry_type IN ('candidate_review', 'blocked_beat_guidance')", name=op.f("ck_visual_review_entries_entry_type")),
        sa.CheckConstraint("alignment_score IS NULL OR alignment_score BETWEEN 0 AND 100", name=op.f("ck_visual_review_entries_score_range")),
        sa.CheckConstraint("decision IS NULL OR decision IN ('accept', 'replace')", name=op.f("ck_visual_review_entries_decision")),
        sa.CheckConstraint("action IS NULL OR action = 'revise_search'", name=op.f("ck_visual_review_entries_action")),
        sa.ForeignKeyConstraint(["review_id"], ["visual_reviews.review_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["beat_id"], ["visual_beats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["beat_candidates.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("review_id", "beat_id", name="uq_visual_review_entries_review_beat"),
    )
    op.create_table(
        "beat_asset_rejections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("beat_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_sha256", sa.String(64), nullable=False),
        sa.Column("review_id", sa.String(36), nullable=False),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.ForeignKeyConstraint(["workflow_id"], ["visual_workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["beat_id"], ["visual_beats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["beat_candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["review_id"], ["visual_reviews.review_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workflow_id", "beat_id", "candidate_id", name="uq_beat_asset_rejections_candidate"),
    )
    op.create_index("ix_beat_asset_rejections_beat_asset", "beat_asset_rejections", ["workflow_id", "beat_id", "asset_id"])
    op.create_index("ix_beat_asset_rejections_beat_sha", "beat_asset_rejections", ["workflow_id", "beat_id", "asset_sha256"])
    op.create_table(
        "beat_selections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("beat_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("asset_sha256", sa.String(64), nullable=False),
        sa.Column("review_id", sa.String(36), nullable=False),
        sa.Column("alignment_score", sa.Integer(), nullable=False),
        sa.Column("lock_compatibility_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="locked"),
        sa.Column("blocked_reason", sa.String(64)),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("alignment_score BETWEEN 90 AND 100", name=op.f("ck_beat_selections_score_acceptance")),
        sa.CheckConstraint("status IN ('locked', 'blocked_missing')", name=op.f("ck_beat_selections_status")),
        sa.ForeignKeyConstraint(["workflow_id"], ["visual_workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["beat_id"], ["visual_beats.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["beat_candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["review_id"], ["visual_reviews.review_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("workflow_id", "beat_id", name="uq_beat_selections_workflow_beat"),
    )
    op.create_index("ix_beat_selections_workflow_asset", "beat_selections", ["workflow_id", "asset_id"])
    op.create_table(
        "asset_review_annotations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("review_id", sa.String(36), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=False, server_default="chatgpt_visual_review"),
        sa.Column("annotations_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=TIMESTAMP),
        sa.CheckConstraint("source_type = 'chatgpt_visual_review'", name=op.f("ck_asset_review_annotations_source_type")),
        sa.ForeignKeyConstraint(["asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["review_id"], ["visual_reviews.review_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("asset_id", "review_id", name="uq_asset_review_annotations_asset_review"),
    )


def downgrade() -> None:
    op.drop_table("asset_review_annotations")
    op.drop_index("ix_beat_selections_workflow_asset", table_name="beat_selections")
    op.drop_table("beat_selections")
    op.drop_index("ix_beat_asset_rejections_beat_sha", table_name="beat_asset_rejections")
    op.drop_index("ix_beat_asset_rejections_beat_asset", table_name="beat_asset_rejections")
    op.drop_table("beat_asset_rejections")
    op.drop_table("visual_review_entries")
    op.drop_table("visual_reviews")
    op.drop_table("visual_review_templates")
    op.drop_index("ix_beat_candidates_package_status", table_name="beat_candidates")
    op.drop_index("ix_beat_candidates_beat_asset", table_name="beat_candidates")
    op.drop_table("beat_candidates")
    op.drop_index("uq_candidate_packages_one_awaiting", table_name="candidate_packages")
    op.drop_index("ix_candidate_packages_workflow_status", table_name="candidate_packages")
    op.drop_table("candidate_packages")
    op.drop_table("visual_beat_revisions")
    op.drop_index("ix_visual_beats_workflow_state", table_name="visual_beats")
    op.drop_table("visual_beats")
    op.drop_index("ix_visual_request_revisions_workflow_revision", table_name="visual_request_revisions")
    op.drop_table("visual_request_revisions")
    op.drop_table("visual_workflows")
