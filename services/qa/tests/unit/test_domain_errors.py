"""The qa errors: pinned slugs, titles and messages."""

from domain_kernel.errors import PROBLEM_TYPE_PREFIX, DomainError
from qa.domain.errors import (
    BusinessNotFoundError,
    DependencyUnavailableError,
    ModelBudgetExceededError,
    QaTenantRequiredError,
    QuestionInvalidError,
)


def test_slugs_and_titles_are_pinned() -> None:
    pinned: dict[type[DomainError], tuple[str, str]] = {
        QaTenantRequiredError: ("qa-tenant-required", "Tenant required for questions"),
        BusinessNotFoundError: ("qa-business-not-found", "Business not found for the question"),
        QuestionInvalidError: ("qa-question-invalid", "Question is invalid"),
        DependencyUnavailableError: (
            "qa-dependency-unavailable",
            "A service the answer depends on is unavailable",
        ),
        ModelBudgetExceededError: (
            "qa-model-budget-exceeded",
            "Model budget for questions is used up",
        ),
    }
    for error, (slug, title) in pinned.items():
        assert (error.type_slug, error.title) == (slug, title)


def test_details_name_what_is_missing() -> None:
    assert "x-tenant-id" in QaTenantRequiredError().detail
    missing = BusinessNotFoundError("b-1")
    assert (missing.business_id, missing.detail) == (
        "b-1",
        "business b-1 has no profile for this tenant",
    )
    assert QuestionInvalidError().type_uri == PROBLEM_TYPE_PREFIX + "qa-question-invalid"
    assert DependencyUnavailableError("rulebook: 502").detail == "rulebook: 502"


def test_a_used_up_budget_passes_on_the_gateways_retry_after() -> None:
    assert ModelBudgetExceededError(retry_after="3600").problem_headers == {"Retry-After": "3600"}
    assert ModelBudgetExceededError(retry_after="soon").problem_headers == {}
    assert ModelBudgetExceededError().problem_headers == {}
