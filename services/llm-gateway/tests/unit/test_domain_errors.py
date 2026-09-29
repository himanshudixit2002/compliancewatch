from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from domain_kernel.errors import PROBLEM_TYPE_PREFIX, DomainError
from llm_gateway.domain.errors import (
    BudgetExceededError,
    FeatureMismatchError,
    ProviderResponseError,
    ProviderUnavailableError,
    UnknownFeatureError,
    UnknownPromptError,
)

ERRORS: list[tuple[type[DomainError], str, str]] = [
    (BudgetExceededError, "llm-budget-exceeded", "LLM budget exceeded"),
    (ProviderUnavailableError, "llm-provider-unavailable", "LLM provider unavailable"),
    (ProviderResponseError, "llm-provider-response-invalid", "LLM provider response invalid"),
    (UnknownPromptError, "llm-prompt-unregistered", "LLM prompt not registered"),
    (UnknownFeatureError, "llm-feature-unknown", "LLM feature unknown"),
    (FeatureMismatchError, "llm-feature-mismatch", "LLM feature mismatch"),
]


@pytest.mark.parametrize(("error_type", "slug", "title"), ERRORS)
def test_slugs_and_titles(error_type: type[DomainError], slug: str, title: str) -> None:
    assert error_type.type_slug == slug
    assert error_type.title == title
    assert issubclass(error_type, DomainError)


def test_slugs_and_titles_are_unique() -> None:
    assert len({slug for _, slug, _ in ERRORS}) == len(ERRORS)
    assert len({title for _, _, title in ERRORS}) == len(ERRORS)


def test_budget_exceeded_carries_the_budget_and_a_retry_after() -> None:
    resets_at = datetime.now(UTC) + timedelta(seconds=3600)
    error = BudgetExceededError(
        "tenant budget used up",
        scope="tenant",
        spent_inr=Decimal("1500.1000"),
        limit_inr=Decimal("1500"),
        resets_at=resets_at,
    )
    assert error.type_uri == PROBLEM_TYPE_PREFIX + "llm-budget-exceeded"
    assert str(error) == "tenant budget used up"
    assert (error.scope, error.spent_inr, error.limit_inr) == (
        "tenant",
        Decimal("1500.1000"),
        Decimal("1500"),
    )
    assert error.resets_at == resets_at
    assert 3500 <= int(error.problem_headers["Retry-After"]) <= 3600


def test_budget_exceeded_defaults() -> None:
    error = BudgetExceededError()
    assert error.detail == "LLM budget exceeded"
    assert error.scope == "gateway"
    assert error.spent_inr is None
    assert error.limit_inr is None
    assert error.problem_headers == {}


def test_budget_exceeded_retry_after_is_at_least_one_second() -> None:
    error = BudgetExceededError(resets_at=datetime.now(UTC) - timedelta(days=1))
    assert error.problem_headers == {"Retry-After": "1"}


def test_provider_unavailable_retry_after() -> None:
    assert ProviderUnavailableError().problem_headers == {}
    assert ProviderUnavailableError("later", retry_after_seconds=2.2).problem_headers == {
        "Retry-After": "3"
    }
    assert ProviderUnavailableError(retry_after_seconds=0).problem_headers == {"Retry-After": "1"}
    assert ProviderUnavailableError(retry_after_seconds=30).retry_after_seconds == 30


def test_provider_response_error_default_message() -> None:
    assert str(ProviderResponseError()) == "LLM provider response invalid"
    assert ProviderResponseError("empty choices").detail == "empty choices"


def test_unknown_prompt_is_a_lookup_error_with_the_reference() -> None:
    error = UnknownPromptError("smoke.echo@9")
    assert error.ref == "smoke.echo@9"
    assert str(error) == "prompt 'smoke.echo@9' is not registered"
    assert isinstance(error, LookupError)


def test_unknown_feature_is_a_value_error_with_the_name() -> None:
    error = UnknownFeatureError("summaries")
    assert error.feature == "summaries"
    assert str(error) == "unknown feature 'summaries'"
    assert isinstance(error, ValueError)
    assert not isinstance(ProviderUnavailableError(), ValueError)
