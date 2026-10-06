"""The rulebook's errors: each has a problem type and a title of its own, and the app answers
each with the status it maps it to."""

import inspect

from domain_kernel.errors import DomainError
from rulebook.domain import errors
from rulebook.main import PROBLEM_STATUS

ERRORS = [
    error
    for _, error in inspect.getmembers(errors, inspect.isclass)
    if issubclass(error, DomainError) and error.__module__ == errors.__name__
]


def test_every_error_has_a_slug_and_a_title_of_its_own() -> None:
    slugs = [error.type_slug for error in ERRORS]
    titles = [error.title for error in ERRORS]
    assert len(set(slugs)) == len(slugs)
    assert len(set(titles)) == len(titles)
    assert all(slug.startswith("rulebook-") for slug in slugs)


def test_every_error_has_its_status() -> None:
    assert set(ERRORS) <= set(PROBLEM_STATUS), "map each error to its status in rulebook.main"


def test_the_candidate_errors_answer_as_the_routes_document() -> None:
    assert PROBLEM_STATUS[errors.RuleCandidateNotFoundError] == 404
    assert PROBLEM_STATUS[errors.CandidateAlreadyDraftedError] == 409
    assert PROBLEM_STATUS[errors.CandidateNotDraftedError] == 409
    assert PROBLEM_STATUS[errors.DraftIncompleteError] == 422
    assert PROBLEM_STATUS[errors.RuleKeyUnknownError] == 422
    assert PROBLEM_STATUS[errors.RuleKeyTakenError] == 409
    assert PROBLEM_STATUS[errors.CandidatePayloadInvalidError] == 422
    assert PROBLEM_STATUS[errors.RuleVersionClosedError] == 409
    incomplete = errors.DraftIncompleteError(["title: missing", "effective_from: missing"])
    assert incomplete.problems == ("title: missing", "effective_from: missing")
    assert incomplete.detail == "title: missing; effective_from: missing"
