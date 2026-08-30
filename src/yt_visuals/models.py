from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


asset_tags = Table(
    "asset_tags",
    Base.metadata,
    Column("asset_id", ForeignKey("media_assets.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "tagged_at", DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    ),
    Index("ix_asset_tags_tag_id", "tag_id"),
)


class MediaAsset(TimestampMixin, Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint("media_type IN ('image', 'video', 'audio')", name="media_type"),
        CheckConstraint("sfx_kind IS NULL OR sfx_kind IN ('one_shot', 'ambient')", name="sfx_kind"),
        CheckConstraint("status IN ('active', 'archived', 'missing')", name="status"),
        CheckConstraint("length(trim(relative_path)) > 0", name="relative_path_not_empty"),
        CheckConstraint("relative_path NOT LIKE '/%'", name="relative_path_not_posix_absolute"),
        CheckConstraint("relative_path NOT GLOB '[A-Za-z]:*'", name="relative_path_not_drive_absolute"),
        CheckConstraint(
            "substr(relative_path, 1, 1) != char(92)", name="relative_path_not_backslash_absolute"
        ),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="file_size_nonnegative"),
        CheckConstraint("width IS NULL OR width > 0", name="width_positive"),
        CheckConstraint("height IS NULL OR height > 0", name="height_positive"),
        CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="duration_nonnegative"),
        CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name="sha256_length"),
        CheckConstraint("sha256 IS NULL OR sha256 NOT GLOB '*[^0-9a-f]*'", name="sha256_lower_hex"),
        CheckConstraint("usage_count >= 0", name="usage_count_nonnegative"),
        Index("ix_media_assets_type_status", "media_type", "status"),
        Index("ix_media_assets_last_used_at", "last_used_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    sfx_kind: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")
    title: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(127))
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), unique=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    file_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    technical_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    sources: Mapped[list["MediaSource"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    license: Mapped["AssetLicense | None"] = relationship(
        back_populates="asset", cascade="all, delete-orphan", single_parent=True
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=asset_tags, back_populates="assets")
    usages: Mapped[list["AssetUsage"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    downloads: Mapped[list["MediaDownload"]] = relationship(back_populates="asset")
    locations: Mapped[list["MediaLocation"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )


class MediaLocation(TimestampMixin, Base):
    __tablename__ = "media_locations"
    __table_args__ = (
        CheckConstraint("status IN ('available', 'missing')", name="status"),
        CheckConstraint(
            "provenance_type IN ('local_import', 'provider_download')", name="provenance_type"
        ),
        CheckConstraint("length(trim(relative_path)) > 0", name="relative_path_not_empty"),
        CheckConstraint("relative_path NOT LIKE '/%'", name="relative_path_not_posix_absolute"),
        CheckConstraint("relative_path NOT GLOB '[A-Za-z]:*'", name="relative_path_not_drive_absolute"),
        CheckConstraint(
            "substr(relative_path, 1, 1) != char(92)", name="relative_path_not_backslash_absolute"
        ),
        CheckConstraint("file_size_bytes IS NULL OR file_size_bytes >= 0", name="file_size_nonnegative"),
        CheckConstraint("file_modified_ns IS NULL OR file_modified_ns >= 0", name="modified_ns_nonnegative"),
        Index("ix_media_locations_asset_status", "media_asset_id", "status"),
        Index("ix_media_locations_status_last_seen", "status", "last_seen_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    relative_path: Mapped[str] = mapped_column(
        String(1024, collation="NOCASE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="available", server_default="available"
    )
    provenance_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer)
    file_modified_ns: Mapped[int | None] = mapped_column(Integer)
    file_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    missing_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    asset: Mapped[MediaAsset] = relationship(back_populates="locations")


class MediaProvider(TimestampMixin, Base):
    __tablename__ = "media_providers"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="name_not_empty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), nullable=False, unique=True)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text)

    sources: Mapped[list["MediaSource"]] = relationship(back_populates="provider")


class MediaSource(TimestampMixin, Base):
    __tablename__ = "media_sources"
    __table_args__ = (
        UniqueConstraint("provider_id", "provider_asset_id", name="uq_media_sources_provider_asset"),
        Index("ix_media_sources_asset_id", "asset_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_providers.id", ondelete="SET NULL")
    )
    provider_asset_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str | None] = mapped_column(String(2048))
    creator_name: Mapped[str | None] = mapped_column(String(255))
    creator_url: Mapped[str | None] = mapped_column(String(2048))
    original_filename: Mapped[str | None] = mapped_column(String(512))
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    asset: Mapped[MediaAsset] = relationship(back_populates="sources")
    provider: Mapped[MediaProvider | None] = relationship(back_populates="sources")


class MediaDownload(TimestampMixin, Base):
    __tablename__ = "media_downloads"
    __table_args__ = (
        CheckConstraint("media_type IN ('image', 'video', 'audio')", name="media_type"),
        CheckConstraint(
            "status IN ('started', 'success', 'failed', 'duplicate', 'reused')", name="status"
        ),
        CheckConstraint("length(trim(provider)) > 0", name="provider_not_empty"),
        CheckConstraint("length(trim(provider_asset_id)) > 0", name="provider_asset_id_not_empty"),
        CheckConstraint("downloaded_bytes IS NULL OR downloaded_bytes >= 0", name="bytes_nonnegative"),
        CheckConstraint(
            "http_status_code IS NULL OR http_status_code BETWEEN 100 AND 599",
            name="http_status_range",
        ),
        CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name="sha256_length"),
        CheckConstraint("sha256 IS NULL OR sha256 NOT GLOB '*[^0-9a-f]*'", name="sha256_lower_hex"),
        CheckConstraint(
            "relative_path IS NULL OR relative_path NOT LIKE '/%'", name="path_not_posix_absolute"
        ),
        CheckConstraint(
            "relative_path IS NULL OR relative_path NOT GLOB '[A-Za-z]:*'",
            name="path_not_drive_absolute",
        ),
        CheckConstraint(
            "relative_path IS NULL OR substr(relative_path, 1, 1) != char(92)",
            name="path_not_backslash_absolute",
        ),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= attempted_at", name="completed_after_attempted"
        ),
        Index("ix_media_downloads_provider_asset_attempted", "provider", "provider_asset_id", "attempted_at"),
        Index("ix_media_downloads_status_attempted", "status", "attempted_at"),
        Index("ix_media_downloads_media_asset_id", "media_asset_id"),
        Index("ix_media_downloads_sha256", "sha256"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(100, collation="NOCASE"), nullable=False)
    provider_asset_id: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048))
    download_url: Mapped[str | None] = mapped_column(String(4096))
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="started", server_default="started")
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    relative_path: Mapped[str | None] = mapped_column(String(1024))
    sha256: Mapped[str | None] = mapped_column(String(64))
    downloaded_bytes: Mapped[int | None] = mapped_column(Integer)
    http_status_code: Mapped[int | None] = mapped_column(Integer)
    content_type: Mapped[str | None] = mapped_column(String(255))
    error_category: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    provider_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    request_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    asset: Mapped[MediaAsset | None] = relationship(back_populates="downloads")


class AssetLicense(TimestampMixin, Base):
    __tablename__ = "asset_licenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    license_name: Mapped[str | None] = mapped_column(String(255))
    license_url: Mapped[str | None] = mapped_column(String(2048))
    attribution_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    attribution_text: Mapped[str | None] = mapped_column(Text)
    usage_terms: Mapped[str | None] = mapped_column(Text)
    commercial_use_allowed: Mapped[bool | None] = mapped_column(Boolean)
    modifications_allowed: Mapped[bool | None] = mapped_column(Boolean)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    asset: Mapped[MediaAsset] = relationship(back_populates="license")


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="name_not_empty"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100, collation="NOCASE"), nullable=False, unique=True)

    assets: Mapped[list[MediaAsset]] = relationship(secondary=asset_tags, back_populates="tags")


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('planning', 'in_progress', 'complete', 'published', 'archived')", name="status"),
        CheckConstraint("season_number IS NULL OR season_number > 0", name="season_positive"),
        CheckConstraint("episode_number IS NULL OR episode_number > 0", name="episode_positive"),
        CheckConstraint("length(trim(slug)) > 0", name="slug_not_empty"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        CheckConstraint("project_path IS NULL OR project_path NOT LIKE '/%'", name="path_not_posix_absolute"),
        CheckConstraint("project_path IS NULL OR project_path NOT GLOB '[A-Za-z]:*'", name="path_not_drive_absolute"),
        CheckConstraint(
            "project_path IS NULL OR substr(project_path, 1, 1) != char(92)",
            name="path_not_backslash_absolute",
        ),
        UniqueConstraint("season_number", "episode_number", name="uq_projects_season_episode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(150, collation="NOCASE"), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="planning", server_default="planning"
    )
    project_path: Mapped[str | None] = mapped_column(String(1024))
    planned_publish_date: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)

    stories: Mapped[list["Story"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="Story.position"
    )
    asset_usages: Mapped[list["AssetUsage"]] = relationship(back_populates="project")


class Story(TimestampMixin, Base):
    __tablename__ = "stories"
    __table_args__ = (
        CheckConstraint("position > 0", name="position_positive"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        CheckConstraint("target_duration_seconds IS NULL OR target_duration_seconds > 0", name="duration_positive"),
        UniqueConstraint("project_id", "position", name="uq_stories_project_position"),
        Index("ix_stories_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    target_duration_seconds: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship(back_populates="stories")
    asset_usages: Mapped[list["AssetUsage"]] = relationship(
        back_populates="story", cascade="all, delete-orphan"
    )


class AssetUsage(TimestampMixin, Base):
    __tablename__ = "asset_usages"
    __table_args__ = (
        CheckConstraint("narration_start_ms IS NULL OR narration_start_ms >= 0", name="start_nonnegative"),
        CheckConstraint("narration_end_ms IS NULL OR narration_end_ms >= 0", name="end_nonnegative"),
        CheckConstraint(
            "narration_start_ms IS NULL OR narration_end_ms IS NULL OR narration_end_ms >= narration_start_ms",
            name="end_after_start",
        ),
        Index("ix_asset_usages_asset_used", "asset_id", "used_at"),
        Index("ix_asset_usages_story_id", "story_id"),
        Index("ix_asset_usages_project_used", "project_id", "used_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE")
    )
    story_id: Mapped[int | None] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"))
    segment_label: Mapped[str | None] = mapped_column(String(255))
    usage_reference: Mapped[str | None] = mapped_column(String(255))
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True)
    narration_start_ms: Mapped[int | None] = mapped_column(Integer)
    narration_end_ms: Mapped[int | None] = mapped_column(Integer)
    usage_role: Mapped[str | None] = mapped_column(String(100))
    used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    notes: Mapped[str | None] = mapped_column(Text)

    asset: Mapped[MediaAsset] = relationship(back_populates="usages")
    project: Mapped[Project | None] = relationship(back_populates="asset_usages")
    story: Mapped[Story | None] = relationship(back_populates="asset_usages")


class VisualWorkflow(TimestampMixin, Base):
    __tablename__ = "visual_workflows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'complete', 'blocked')", name="status"
        ),
        CheckConstraint("length(trim(story_external_id)) > 0", name="story_external_id_not_empty"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active", server_default="active")


class VisualRequestRevision(TimestampMixin, Base):
    __tablename__ = "visual_request_revisions"
    __table_args__ = (
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("length(document_sha256) = 64", name="document_sha256_length"),
        UniqueConstraint("workflow_id", "revision", name="uq_visual_request_revisions_workflow_revision"),
        Index("ix_visual_request_revisions_workflow_revision", "workflow_id", "revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("visual_workflows.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class VisualBeat(TimestampMixin, Base):
    __tablename__ = "visual_beats"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending', 'sourcing', 'review_required', 'rejected', "
            "'blocked_no_candidate', 'accepted_locked', 'blocked_missing')",
            name="state",
        ),
        UniqueConstraint("workflow_id", "external_beat_id", name="uq_visual_beats_workflow_external"),
        Index("ix_visual_beats_workflow_state", "workflow_id", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("visual_workflows.id", ondelete="CASCADE"), nullable=False
    )
    external_beat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")


class VisualBeatRevision(TimestampMixin, Base):
    __tablename__ = "visual_beat_revisions"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("length(lock_compatibility_sha256) = 64", name="compatibility_sha256_length"),
        UniqueConstraint("request_revision_id", "beat_id", name="uq_visual_beat_revisions_request_beat"),
        UniqueConstraint("request_revision_id", "sequence", name="uq_visual_beat_revisions_request_sequence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_revision_id: Mapped[str] = mapped_column(
        ForeignKey("visual_request_revisions.id", ondelete="CASCADE"), nullable=False
    )
    beat_id: Mapped[str] = mapped_column(
        ForeignKey("visual_beats.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    lock_compatibility_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class CandidatePackage(TimestampMixin, Base):
    __tablename__ = "candidate_packages"
    __table_args__ = (
        CheckConstraint("iteration > 0", name="iteration_positive"),
        CheckConstraint(
            "status IN ('building', 'awaiting_review', 'reviewed', 'generation_failed')",
            name="status",
        ),
        UniqueConstraint("workflow_id", "iteration", name="uq_candidate_packages_workflow_iteration"),
        UniqueConstraint("review_id", name="uq_candidate_packages_review_id"),
        Index("ix_candidate_packages_workflow_status", "workflow_id", "status"),
        Index(
            "uq_candidate_packages_one_awaiting",
            "workflow_id",
            unique=True,
            sqlite_where=text("status = 'awaiting_review'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("visual_workflows.id", ondelete="CASCADE"), nullable=False
    )
    request_revision_id: Mapped[str] = mapped_column(
        ForeignKey("visual_request_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    iteration: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="building", server_default="building")
    candidate_report_path: Mapped[str | None] = mapped_column(String(1024))
    candidate_report_sha256: Mapped[str | None] = mapped_column(String(64))
    storyboard_path: Mapped[str | None] = mapped_column(String(1024))
    storyboard_sha256: Mapped[str | None] = mapped_column(String(64))
    review_template_path: Mapped[str | None] = mapped_column(String(1024))
    review_template_sha256: Mapped[str | None] = mapped_column(String(64))
    review_id: Mapped[str] = mapped_column(String(36), nullable=False)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BeatCandidate(TimestampMixin, Base):
    __tablename__ = "beat_candidates"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'rejected', 'accepted', 'locked_carried')", name="status"
        ),
        UniqueConstraint("package_id", "beat_id", name="uq_beat_candidates_package_beat"),
        Index("ix_beat_candidates_beat_asset", "beat_id", "asset_id"),
        Index("ix_beat_candidates_package_status", "package_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_packages.id", ondelete="CASCADE"), nullable=False
    )
    beat_id: Mapped[str] = mapped_column(
        ForeignKey("visual_beats.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="proposed", server_default="proposed")
    retrieval_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    preview_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class VisualReviewTemplate(TimestampMixin, Base):
    __tablename__ = "visual_review_templates"
    __table_args__ = (UniqueConstraint("package_id", name="uq_visual_review_templates_package"),)

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    package_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_packages.id", ondelete="CASCADE"), nullable=False
    )
    template_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    template_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class VisualReview(TimestampMixin, Base):
    __tablename__ = "visual_reviews"

    review_id: Mapped[str] = mapped_column(
        ForeignKey("visual_review_templates.review_id", ondelete="CASCADE"), primary_key=True
    )
    completed_document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class VisualReviewEntry(TimestampMixin, Base):
    __tablename__ = "visual_review_entries"
    __table_args__ = (
        CheckConstraint(
            "entry_type IN ('candidate_review', 'blocked_beat_guidance')", name="entry_type"
        ),
        CheckConstraint("alignment_score IS NULL OR alignment_score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("decision IS NULL OR decision IN ('accept', 'replace')", name="decision"),
        CheckConstraint("action IS NULL OR action = 'revise_search'", name="action"),
        UniqueConstraint("review_id", "beat_id", name="uq_visual_review_entries_review_beat"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("visual_reviews.review_id", ondelete="CASCADE"), nullable=False
    )
    beat_id: Mapped[str] = mapped_column(
        ForeignKey("visual_beats.id", ondelete="CASCADE"), nullable=False
    )
    entry_type: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_id: Mapped[str | None] = mapped_column(
        ForeignKey("beat_candidates.id", ondelete="RESTRICT")
    )
    alignment_score: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str | None] = mapped_column(String(32))
    mismatch_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    replacement_guidance_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    catalog_annotations_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class BeatAssetRejection(TimestampMixin, Base):
    __tablename__ = "beat_asset_rejections"
    __table_args__ = (
        UniqueConstraint("workflow_id", "beat_id", "candidate_id", name="uq_beat_asset_rejections_candidate"),
        Index("ix_beat_asset_rejections_beat_asset", "workflow_id", "beat_id", "asset_id"),
        Index("ix_beat_asset_rejections_beat_sha", "workflow_id", "beat_id", "asset_sha256"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("visual_workflows.id", ondelete="CASCADE"), nullable=False
    )
    beat_id: Mapped[str] = mapped_column(
        ForeignKey("visual_beats.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("beat_candidates.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("visual_reviews.review_id", ondelete="RESTRICT"), nullable=False
    )
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class BeatSelection(TimestampMixin, Base):
    __tablename__ = "beat_selections"
    __table_args__ = (
        CheckConstraint("alignment_score BETWEEN 90 AND 100", name="score_acceptance"),
        CheckConstraint("status IN ('locked', 'blocked_missing')", name="status"),
        UniqueConstraint("workflow_id", "beat_id", name="uq_beat_selections_workflow_beat"),
        Index("ix_beat_selections_workflow_asset", "workflow_id", "asset_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("visual_workflows.id", ondelete="CASCADE"), nullable=False
    )
    beat_id: Mapped[str] = mapped_column(
        ForeignKey("visual_beats.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("beat_candidates.id", ondelete="RESTRICT"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    asset_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    review_id: Mapped[str] = mapped_column(
        ForeignKey("visual_reviews.review_id", ondelete="RESTRICT"), nullable=False
    )
    alignment_score: Mapped[int] = mapped_column(Integer, nullable=False)
    lock_compatibility_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="locked", server_default="locked")
    blocked_reason: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class AssetReviewAnnotation(TimestampMixin, Base):
    __tablename__ = "asset_review_annotations"
    __table_args__ = (
        CheckConstraint("source_type = 'chatgpt_visual_review'", name="source_type"),
        UniqueConstraint("asset_id", "review_id", name="uq_asset_review_annotations_asset_review"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    review_id: Mapped[str] = mapped_column(
        ForeignKey("visual_reviews.review_id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default="chatgpt_visual_review", server_default="chatgpt_visual_review"
    )
    annotations_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ProducerWorkspace(TimestampMixin, Base):
    __tablename__ = "producer_workspaces"
    __table_args__ = (
        CheckConstraint("status IN ('planned', 'in_production', 'completed')", name="status"),
        CheckConstraint("length(trim(story_external_id)) > 0", name="story_external_id_not_empty"),
        CheckConstraint("length(trim(title)) > 0", name="title_not_empty"),
        CheckConstraint("length(plan_document_sha256) = 64", name="plan_sha256_length"),
        Index("ix_producer_workspaces_release_position", "video_release_id", "release_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    story_external_id: Mapped[str] = mapped_column(
        String(128, collation="NOCASE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_document_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="in_production", server_default="in_production"
    )
    video_release_id: Mapped[str | None] = mapped_column(
        ForeignKey("video_releases.id", ondelete="RESTRICT"), nullable=True
    )
    release_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edit_plan_document_sha256: Mapped[str | None] = mapped_column(String(64))
    edit_plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    edit_plan_imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    beats: Mapped[list["ProducerBeat"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan", order_by="ProducerBeat.sequence"
    )
    video_release: Mapped["VideoRelease | None"] = relationship(back_populates="workspaces")


class VideoRelease(TimestampMixin, Base):
    __tablename__ = "video_releases"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="name_not_empty"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255, collation="NOCASE"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="planned", server_default="planned"
    )
    release_date: Mapped[date | None] = mapped_column(Date)
    workspaces: Mapped[list["ProducerWorkspace"]] = relationship(
        back_populates="video_release",
        order_by="ProducerWorkspace.release_position",
    )
    presentation_revisions: Mapped[list["ReleasePresentationRevision"]] = relationship(
        back_populates="video_release",
        order_by="ReleasePresentationRevision.sequence",
    )


class ReleasePresentationRevision(Base):
    __tablename__ = "release_presentation_revisions"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint("length(trim(public_title)) > 0", name="public_title_not_empty"),
        CheckConstraint("length(trim(source)) > 0", name="source_not_empty"),
        UniqueConstraint(
            "video_release_id", "sequence", name="uq_release_presentation_release_sequence"
        ),
        Index(
            "ix_release_presentation_release_created",
            "video_release_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    video_release_id: Mapped[str] = mapped_column(
        ForeignKey("video_releases.id", ondelete="RESTRICT"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    public_title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT")
    )
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="producer_ui", server_default="producer_ui"
    )
    change_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )

    video_release: Mapped[VideoRelease] = relationship(back_populates="presentation_revisions")
    thumbnail_asset: Mapped[MediaAsset | None] = relationship()


class ProductionEvent(Base):
    __tablename__ = "production_events"
    __table_args__ = (
        CheckConstraint("subject_type IN ('release', 'workspace')", name="subject_type"),
        CheckConstraint("length(trim(event_type)) > 0", name="event_type_not_empty"),
        CheckConstraint("length(trim(source)) > 0", name="source_not_empty"),
        CheckConstraint("payload_schema_version > 0", name="payload_schema_version_positive"),
        CheckConstraint(
            "(related_subject_type IS NULL) = (related_subject_id IS NULL)",
            name="related_subject_pair",
        ),
        CheckConstraint(
            "related_subject_type IS NULL OR related_subject_type IN ('release', 'workspace')",
            name="related_subject_type",
        ),
        Index("ix_production_events_subject_time", "subject_type", "subject_id", "occurred_at"),
        Index(
            "ix_production_events_related_time",
            "related_subject_type",
            "related_subject_id",
            "occurred_at",
        ),
        Index("ix_production_events_type_time", "event_type", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(36), nullable=False)
    related_subject_type: Mapped[str | None] = mapped_column(String(16))
    related_subject_id: Mapped[str | None] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, default="producer_ui", server_default="producer_ui"
    )
    payload_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ProducerBeat(TimestampMixin, Base):
    __tablename__ = "producer_beats"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="sequence_positive"),
        CheckConstraint(
            "selected_asset_sha256 IS NULL OR length(selected_asset_sha256) = 64",
            name="selected_sha256_length",
        ),
        UniqueConstraint("workspace_id", "external_beat_id", name="uq_producer_beats_workspace_external"),
        UniqueConstraint("workspace_id", "sequence", name="uq_producer_beats_workspace_sequence"),
        Index("ix_producer_beats_workspace_sequence", "workspace_id", "sequence"),
        Index("ix_producer_beats_selected_sfx_asset_id", "selected_sfx_asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("producer_workspaces.id", ondelete="CASCADE"), nullable=False
    )
    external_beat_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    specification_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    selected_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT")
    )
    selected_asset_sha256: Mapped[str | None] = mapped_column(String(64))
    selected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Migration 0009 enforces ON DELETE RESTRICT. SQLite cannot reflect options on
    # an ALTER TABLE ADD COLUMN reference, so repeating it here creates false drift.
    selected_sfx_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id")
    )
    selected_sfx_asset_sha256: Mapped[str | None] = mapped_column(String(64))
    selected_sfx_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edit_motion_recommendation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    edit_transition_recommendation_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    producer_motion_type: Mapped[str | None] = mapped_column(String(24))
    producer_motion_target: Mapped[str | None] = mapped_column(Text)
    producer_transition_type: Mapped[str | None] = mapped_column(String(24))
    edit_guidance_asset_sha256: Mapped[str | None] = mapped_column(String(64))
    edit_guidance_needs_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )

    workspace: Mapped[ProducerWorkspace] = relationship(back_populates="beats")
    selected_asset: Mapped[MediaAsset | None] = relationship(
        foreign_keys=[selected_asset_id]
    )
    selected_sfx_asset: Mapped[MediaAsset | None] = relationship(
        foreign_keys=[selected_sfx_asset_id]
    )
    hidden_assets: Mapped[list["ProducerBeatHiddenAsset"]] = relationship(
        back_populates="beat", cascade="all, delete-orphan"
    )


class ProducerBeatHiddenAsset(TimestampMixin, Base):
    __tablename__ = "producer_beat_hidden_assets"
    __table_args__ = (
        UniqueConstraint("beat_id", "asset_id", name="uq_producer_hidden_beat_asset"),
        Index("ix_producer_hidden_beat", "beat_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    beat_id: Mapped[str] = mapped_column(
        ForeignKey("producer_beats.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    hidden_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )

    beat: Mapped[ProducerBeat] = relationship(back_populates="hidden_assets")
    asset: Mapped[MediaAsset] = relationship()
