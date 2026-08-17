from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ServiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SearchMediaRequest(ServiceModel):
    query: str = ""
    media_type: Literal["image", "video"] | None = None
    orientation: Literal["landscape", "portrait", "square"] | None = None
    mime_type: str | None = None
    min_width: int | None = Field(default=None, gt=0)
    min_height: int | None = Field(default=None, gt=0)
    min_duration_ms: int | None = Field(default=None, ge=0)
    max_duration_ms: int | None = Field(default=None, ge=0)
    provider: str | None = None
    tags: tuple[str, ...] = ()
    creator: str | None = None
    usage: Literal["used", "unused"] | None = None
    availability: Literal["available", "missing", "any"] = "available"
    recently_used_within_days: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    story_id: int | None = Field(default=None, gt=0)
    limit: int = Field(default=100, ge=1, le=500)

    @model_validator(mode="after")
    def validate_ranges(self) -> "SearchMediaRequest":
        if (
            self.min_duration_ms is not None
            and self.max_duration_ms is not None
            and self.max_duration_ms < self.min_duration_ms
        ):
            raise ValueError("max_duration_ms must be greater than or equal to min_duration_ms")
        if any(not tag for tag in self.tags):
            raise ValueError("tags cannot contain empty values")
        return self


class MediaLocationResult(ServiceModel):
    relative_path: str
    status: Literal["available", "missing"]
    provenance_type: Literal["local_import", "provider_download"]
    file_size_bytes: int | None
    file_modified_at: datetime | None
    first_seen_at: datetime
    last_seen_at: datetime
    missing_since: datetime | None


class MediaSourceResult(ServiceModel):
    provider: str | None
    provider_website_url: str | None
    provider_asset_id: str | None
    source_url: str | None
    creator_name: str | None
    creator_url: str | None
    original_filename: str | None
    acquired_at: datetime | None


class LicenseResult(ServiceModel):
    license_name: str | None
    license_url: str | None
    attribution_required: bool
    attribution_text: str | None
    usage_terms: str | None
    commercial_use_allowed: bool | None
    modifications_allowed: bool | None
    verified_at: datetime | None


class UsageResult(ServiceModel):
    usage_id: int
    asset_id: int
    project_id: int | None
    project_slug: str | None
    project_title: str | None
    story_id: int | None
    story_position: int | None
    story_title: str | None
    usage_reference: str | None
    segment_label: str | None
    narration_start_ms: int | None
    narration_end_ms: int | None
    usage_role: str | None
    used_at: datetime
    notes: str | None
    idempotency_key: str | None


class SearchCandidateResult(ServiceModel):
    rank: int
    score: int
    score_reasons: tuple[str, ...]
    asset_id: int
    relative_path: str
    current_location: str | None
    media_type: Literal["image", "video"]
    mime_type: str | None
    extension: str
    width: int | None
    height: int | None
    orientation: Literal["landscape", "portrait", "square"] | None
    duration_ms: int | None
    file_size_bytes: int | None
    sha256: str | None
    available: bool
    locations: tuple[str, ...]
    providers: tuple[str, ...]
    creators: tuple[str, ...]
    tags: tuple[str, ...]
    usage_count: int
    recent_usage_count: int
    last_used_at: datetime | None


class SearchMediaResult(ServiceModel):
    query: str
    returned: int
    candidates: tuple[SearchCandidateResult, ...]


class AssetDetailResult(ServiceModel):
    asset_id: int
    relative_path: str
    current_location: str | None
    media_type: Literal["image", "video"]
    mime_type: str | None
    extension: str
    width: int | None
    height: int | None
    orientation: Literal["landscape", "portrait", "square"] | None
    duration_ms: int | None
    file_size_bytes: int | None
    sha256: str | None
    status: Literal["active", "archived", "missing"]
    available: bool
    title: str | None
    description: str | None
    imported_at: datetime
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    locations: tuple[MediaLocationResult, ...]
    sources: tuple[MediaSourceResult, ...]
    license: LicenseResult | None
    tags: tuple[str, ...]
    usage_count: int
    last_used_at: datetime | None
    recent_usage: tuple[UsageResult, ...]
    technical_metadata: dict[str, Any] | None


class LibraryStatusResult(ServiceModel):
    total_assets: int
    available_assets: int
    missing_assets: int
    images: int
    videos: int
    available_locations: int
    missing_locations: int
    duplicate_physical_locations: int
    local_import_locations: int
    provider_download_locations: int
    unused_assets: int
    recently_used_assets: int
    total_available_bytes: int
    recent_window_days: int
    last_scan_at: datetime | None
    last_scan_status: str | None


class RecentUsageRequest(ServiceModel):
    asset_id: int | None = Field(default=None, gt=0)
    project_id: int | None = Field(default=None, gt=0)
    story_id: int | None = Field(default=None, gt=0)
    used_from: datetime | None = None
    used_to: datetime | None = None
    limit: int = Field(default=50, ge=1, le=500)

    @model_validator(mode="after")
    def validate_dates(self) -> "RecentUsageRequest":
        if self.used_from and self.used_to and self.used_to < self.used_from:
            raise ValueError("used_to must be greater than or equal to used_from")
        return self


class RecentUsageResult(ServiceModel):
    returned: int
    usages: tuple[UsageResult, ...]


class RecordUsageRequest(ServiceModel):
    asset_id: int = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=255)
    project_id: int | None = Field(default=None, gt=0)
    story_id: int | None = Field(default=None, gt=0)
    usage_reference: str | None = Field(default=None, max_length=255)
    segment_label: str | None = Field(default=None, max_length=255)
    narration_start_ms: int | None = Field(default=None, ge=0)
    narration_end_ms: int | None = Field(default=None, ge=0)
    usage_role: str | None = Field(default=None, max_length=100)
    used_at: datetime | None = None
    notes: str | None = None
    allow_missing: bool = False

    @model_validator(mode="after")
    def validate_narration_range(self) -> "RecordUsageRequest":
        if (
            self.narration_start_ms is not None
            and self.narration_end_ms is not None
            and self.narration_end_ms < self.narration_start_ms
        ):
            raise ValueError("narration_end_ms must be greater than or equal to narration_start_ms")
        return self


class RecordUsageResult(ServiceModel):
    created: bool
    usage: UsageResult
    asset_usage_count: int
    asset_last_used_at: datetime | None
