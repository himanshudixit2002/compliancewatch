"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from domain_kernel.protocols import LLMProvider
from qa.application.ask import AskQuestion
from qa.domain.ports import (
    ClauseSearch,
    Embedder,
    ObligationReader,
    ProfileReader,
    RulebookReader,
    Tracer,
)
from qa.settings import QaSettings


@dataclass(frozen=True, slots=True)
class Ports:
    """The services and the tracer the use cases run on: HTTP clients and OpenTelemetry in the
    service, memory fakes and a scripted model in tests and evals."""

    rulebook: RulebookReader
    search: ClauseSearch
    profiles: ProfileReader
    obligations: ObligationReader
    embedder: Embedder
    provider: LLMProvider
    tracer: Tracer


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: QaSettings
    ask: AskQuestion
    prompts_ready: Callable[[], Awaitable[bool]]
    today: Callable[[], date]
    """The default question date: today in India."""
