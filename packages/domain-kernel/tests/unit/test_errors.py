import re

from domain_kernel.errors import (
    PROBLEM_TYPE_PREFIX,
    DomainError,
    InvalidAttributeValueError,
    InvalidOperatorError,
    InvalidTransitionError,
    InvariantViolationError,
    OntologyDefinitionError,
    UnknownAttributeError,
    UnknownClosureReasonError,
)

_SLUG = re.compile(r"[a-z][a-z0-9-]*")


def _all_error_types() -> list[type[DomainError]]:
    found: list[type[DomainError]] = []
    pending: list[type[DomainError]] = [DomainError]
    while pending:
        current = pending.pop()
        found.append(current)
        pending.extend(current.__subclasses__())
    return found


def test_every_error_has_a_unique_well_formed_slug() -> None:
    types = _all_error_types()
    slugs = [error_type.type_slug for error_type in types]
    assert len(types) >= 8
    assert len(set(slugs)) == len(slugs)
    assert all(_SLUG.fullmatch(slug) for slug in slugs)


def test_every_error_has_a_unique_title() -> None:
    titles = [error_type.title for error_type in _all_error_types()]
    assert len(set(titles)) == len(titles)
    assert all(title.strip() == title and title for title in titles)


def test_every_error_name_ends_in_error() -> None:
    assert all(error_type.__name__.endswith("Error") for error_type in _all_error_types())


def test_type_uri_uses_the_shared_prefix() -> None:
    assert DomainError().type_uri == PROBLEM_TYPE_PREFIX + "domain-error"
    assert InvariantViolationError().type_uri == PROBLEM_TYPE_PREFIX + "invariant-violation"
    assert PROBLEM_TYPE_PREFIX.startswith("urn:compliancewatch:")


def test_default_message_is_the_title() -> None:
    error = InvariantViolationError()
    assert str(error) == error.title
    assert error.detail == error.title
    assert str(DomainError()) == "Domain error"


def test_detail_becomes_the_message() -> None:
    error = OntologyDefinitionError("version is missing")
    assert str(error) == "version is missing"
    assert error.detail == "version is missing"
    assert error.args == ("version is missing",)


def test_unknown_attribute_carries_the_key() -> None:
    error = UnknownAttributeError("turnover")
    assert error.attribute == "turnover"
    assert "turnover" in str(error)
    assert UnknownAttributeError("x", "custom").detail == "custom"


def test_invalid_attribute_value_carries_key_and_reason() -> None:
    error = InvalidAttributeValueError("employee_count", "-1 is below the minimum 0")
    assert error.attribute == "employee_count"
    assert error.reason == "-1 is below the minimum 0"
    assert str(error) == "employee_count: -1 is below the minimum 0"


def test_invalid_operator_carries_the_triple() -> None:
    error = InvalidOperatorError("state_codes", "gt", "enum_set")
    assert (error.attribute, error.operator, error.attribute_type) == (
        "state_codes",
        "gt",
        "enum_set",
    )
    assert "gt" in str(error)
    assert "enum_set" in str(error)


def test_invalid_transition_carries_both_states() -> None:
    error = InvalidTransitionError("draft", "published")
    assert (error.current, error.new) == ("draft", "published")
    assert "draft" in str(error)
    assert "published" in str(error)


def test_unknown_closure_reason_carries_the_reason() -> None:
    error = UnknownClosureReasonError("nope")
    assert error.reason == "nope"
    assert "nope" in str(error)


def test_mixins_let_callers_catch_builtin_families() -> None:
    assert isinstance(InvariantViolationError(), ValueError)
    assert isinstance(OntologyDefinitionError(), ValueError)
    assert isinstance(UnknownAttributeError("k"), LookupError)
    assert isinstance(InvalidAttributeValueError("k", "why"), ValueError)
    assert isinstance(InvalidOperatorError("k", "gt", "enum"), ValueError)
    assert isinstance(UnknownClosureReasonError("x"), ValueError)
    assert not isinstance(InvalidTransitionError("a", "b"), ValueError)
    assert all(issubclass(error_type, DomainError) for error_type in _all_error_types())
