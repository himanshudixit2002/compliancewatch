"""Every problem any hosted service or the composition root answers has its own type and title.

The combined app turns each ``DomainError`` into a problem whose ``type`` ends in the error's
slug, so two errors with one slug, or one title, would be one problem to a client. Every module
of every service and of the shared packages is imported, so no error class is missed.
"""

import importlib
import pkgutil
from collections import Counter

import pytest

from cw_mvp.errors import RouteNotFoundError
from domain_kernel.errors import DomainError

PACKAGES = (
    "identity",
    "profile_service",
    "rulebook",
    "applicability_engine",
    "obligation",
    "notification",
    "qa",
    "llm_gateway",
    "eval_service",
    "pipeline",
    "py_common",
    "domain_kernel",
    "ontology",
    "cw_mvp",
)


def _every_error() -> list[type[DomainError]]:
    for name in PACKAGES:
        package = importlib.import_module(name)
        for module in pkgutil.walk_packages(package.__path__, f"{name}."):
            if module.name.rsplit(".", 1)[-1] != "__main__":
                importlib.import_module(module.name)
    found: list[type[DomainError]] = []
    pending: list[type[DomainError]] = [DomainError]
    while pending:
        current = pending.pop()
        found.append(current)
        pending.extend(current.__subclasses__())
    return found


@pytest.fixture(scope="module")
def errors() -> list[type[DomainError]]:
    return _every_error()


def _repeated(values: list[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def test_every_error_has_a_unique_type(errors: list[type[DomainError]]) -> None:
    assert RouteNotFoundError in errors
    assert len(errors) > 100
    assert _repeated([error.type_slug for error in errors]) == []


def test_every_error_has_a_unique_title(errors: list[type[DomainError]]) -> None:
    assert _repeated([error.title for error in errors]) == []


def test_the_route_problem_names_itself() -> None:
    error = RouteNotFoundError()
    assert error.type_uri == "urn:compliancewatch:problem:route-not-found"
    assert error.detail == "Route not found"
