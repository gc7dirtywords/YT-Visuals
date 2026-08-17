from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for provider-facing errors safe to display to CLI users."""


class MissingProviderCredentialError(ProviderError):
    pass


class ProviderRequestError(ProviderError):
    pass


class ProviderAuthenticationError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    def __init__(self, message: str, *, reset_at: str | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class ProviderNotFoundError(ProviderError):
    pass


class ProviderConnectionError(ProviderError):
    pass


class ProviderTimeoutError(ProviderError):
    pass


class ProviderResponseError(ProviderError):
    pass


class MediaDownloadError(ProviderError):
    pass
