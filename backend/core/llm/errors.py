"""Error taxonomy shared by every LLM provider.

The router decides what to do (retry, cool down, fall back) purely from the
exception type, so providers must map their transport errors onto these.
"""
from __future__ import annotations

from typing import Optional


class LLMError(Exception):
    """Base class. `provider` is the provider name that raised it."""

    def __init__(self, message: str, provider: str = "", retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class RateLimitError(LLMError):
    """HTTP 429 / quota exhausted.

    retry_after: seconds the server asked us to wait (None if not given).
    scope: "daily" when the daily quota is exhausted (retrying soon is
           pointless), otherwise "unknown" (typically per-minute).
    """

    def __init__(self, message: str, provider: str = "",
                 retry_after: Optional[float] = None, scope: str = "unknown"):
        super().__init__(message, provider, retryable=(scope != "daily"))
        self.retry_after = retry_after
        self.scope = scope


class ProviderUnavailableError(LLMError):
    """Network failure, timeout, or 5xx. `retryable` says whether a retry is sensible."""


class AuthError(LLMError):
    """Missing/invalid API key or permission problem. Never retryable."""


class BadRequestError(LLMError):
    """Request rejected (bad model name, bad payload). Never retryable."""


class ContentBlockedError(LLMError):
    """Provider refused to answer (safety filter). Never retryable on that provider."""


class AllProvidersFailedError(LLMError):
    """Every candidate provider failed or was skipped. `attempts` explains why."""

    def __init__(self, message: str, attempts: list):
        super().__init__(message, provider="router")
        self.attempts = attempts
