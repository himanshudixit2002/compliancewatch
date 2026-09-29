"""Errors of the qa service, with stable problem type slugs.

``GatewayError`` is a plain exception: the planner turns it into a fallback and the answerer
into ``DependencyUnavailableError``, so it never leaves the service as it is.
"""

from collections.abc import Mapping

from domain_kernel.errors import DomainError


class QaTenantRequiredError(DomainError, PermissionError):
    type_slug = "qa-tenant-required"
    title = "Tenant required for questions"

    def __init__(self) -> None:
        super().__init__("the request names no tenant (x-tenant-id header)")


class BusinessNotFoundError(DomainError, LookupError):
    type_slug = "qa-business-not-found"
    title = "Business not found for the question"

    def __init__(self, business_id: str) -> None:
        super().__init__(f"business {business_id} has no profile for this tenant")
        self.business_id = business_id


class QuestionInvalidError(DomainError, ValueError):
    type_slug = "qa-question-invalid"
    title = "Question is invalid"


class DependencyUnavailableError(DomainError):
    """A service the answer is built from did not answer, failed, or refused the call."""

    type_slug = "qa-dependency-unavailable"
    title = "A service the answer depends on is unavailable"


class ModelBudgetExceededError(DomainError):
    """The llm-gateway refused a model call because a monthly budget (the tenant's, the
    feature's or the gateway's own) is used up. It is not an outage: no other layer can answer
    without the model, so the question ends here, with the gateway's ``Retry-After``."""

    type_slug = "qa-model-budget-exceeded"
    title = "Model budget for questions is used up"

    def __init__(self, detail: str = "", *, retry_after: str | None = None) -> None:
        self.retry_after = retry_after if retry_after and retry_after.isdigit() else None
        super().__init__(detail)

    @property
    def problem_headers(self) -> Mapping[str, str]:
        return {} if self.retry_after is None else {"Retry-After": self.retry_after}


class GatewayError(RuntimeError):
    """The llm-gateway refused or failed a completion; the text is the status and problem."""
