"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from applicability_engine.application.evaluate import EvaluateRule
from applicability_engine.application.queries import ListDecisions, ReadDecision
from applicability_engine.domain.ports import ProfileReader, RulebookReader
from applicability_engine.domain.repository import UnitOfWorkFactory
from applicability_engine.settings import ApplicabilityEngineSettings
from py_common.idempotency import IdempotencyStore


@dataclass(frozen=True, slots=True)
class Readers:
    """Where decisions are computed from: HTTP clients in the app, memory fakes in tests."""

    profiles: ProfileReader
    rulebook: RulebookReader


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: ApplicabilityEngineSettings
    unit_of_work: UnitOfWorkFactory
    store_ready: Callable[[], Awaitable[bool]]
    idempotency: IdempotencyStore
    evaluate: EvaluateRule
    list_decisions: ListDecisions
    read_decision: ReadDecision
