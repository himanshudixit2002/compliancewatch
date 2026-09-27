"""Errors the gateway raises. Each has a unique problem type slug and title.

The API maps them to statuses; ``problem_headers`` adds response headers such as ``Retry-After``.
"""

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal

from domain_kernel.errors import DomainError


class BudgetExceededError(DomainError):
    """A monthly budget (tenant, feature or the upstream gateway's own) is used up."""

    type_slug = "llm-budget-exceeded"
    title = "LLM budget exceeded"

    def __init__(
        self,
        detail: str = "",
        *,
        scope: str = "gateway",
        spent_inr: Decimal | None = None,
        limit_inr: Decimal | None = None,
        resets_at: datetime | None = None,
    ) -> None:
        self.scope = scope
        self.spent_inr = spent_inr
        self.limit_inr = limit_inr
        self.resets_at = resets_at
        super().__init__(detail)

    @property
    def problem_headers(self) -> Mapping[str, str]:
        """``Retry-After`` in whole seconds until the budget resets, when that is known."""
        if self.resets_at is None:
            return {}
        remaining = (self.resets_at - datetime.now(UTC)).total_seconds()
        return {"Retry-After": str(max(1, int(remaining)))}


class ProviderUnavailableError(DomainError):
    """The provider could not serve the call now: outage, rate limit, open circuit."""

    type_slug = "llm-provider-unavailable"
    title = "LLM provider unavailable"

    def __init__(self, detail: str = "", *, retry_after_seconds: float | None = None) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)

    @property
    def problem_headers(self) -> Mapping[str, str]:
        if self.retry_after_seconds is None:
            return {}
        return {"Retry-After": str(max(1, math.ceil(self.retry_after_seconds)))}


class ProviderResponseError(DomainError):
    """The provider answered, but not with something the gateway can use."""

    type_slug = "llm-provider-response-invalid"
    title = "LLM provider response invalid"


class UnknownPromptError(DomainError, LookupError):
    """The prompt reference is not in the registry."""

    type_slug = "llm-prompt-unregistered"
    title = "LLM prompt not registered"

    def __init__(self, ref: str) -> None:
        self.ref = ref
        super().__init__(f"prompt {ref!r} is not registered")


class UnknownFeatureError(DomainError, ValueError):
    """A feature name outside the ``Feature`` enum."""

    type_slug = "llm-feature-unknown"
    title = "LLM feature unknown"

    def __init__(self, feature: str) -> None:
        self.feature = feature
        super().__init__(f"unknown feature {feature!r}")
