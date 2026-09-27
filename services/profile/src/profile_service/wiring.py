"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from domain_kernel.ontology import Ontology
from profile_service.application.attributes import (
    BuildSnapshot,
    ConfirmFinancialYear,
    NextQuestion,
    SetAttributes,
)
from profile_service.application.registration import RegisterNodes
from profile_service.domain.repository import UnitOfWorkFactory
from profile_service.settings import ProfileSettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: ProfileSettings
    ontology: Ontology
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    register: RegisterNodes
    set_attributes: SetAttributes
    next_question: NextQuestion
    build_snapshot: BuildSnapshot
    confirm_financial_year: ConfirmFinancialYear
