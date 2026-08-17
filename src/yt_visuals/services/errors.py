from __future__ import annotations

from typing import Any


class MediaServiceError(RuntimeError):
    code = "media_service_error"

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}


class AssetNotFoundError(MediaServiceError):
    code = "asset_not_found"


class AssetUnavailableError(MediaServiceError):
    code = "asset_unavailable"


class InvalidFilterError(MediaServiceError):
    code = "invalid_filter"


class InvalidUsageReferenceError(MediaServiceError):
    code = "invalid_usage_reference"


class CatalogDatabaseError(MediaServiceError):
    code = "database_failure"
