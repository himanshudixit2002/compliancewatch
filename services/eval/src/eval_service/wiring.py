"""What the API layer gets from the composition root, typed by protocols and use cases only, so
the api package never imports infrastructure (import-linter keeps api and infrastructure apart)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from eval_service.application.queries import GetEvalRun, ListEvalRuns
from eval_service.application.run_eval import RunEvalSuite
from eval_service.settings import EvalSettings


@dataclass(frozen=True, slots=True)
class Wiring:
    settings: EvalSettings
    store_ready: Callable[[], Awaitable[bool]]
    run_suite: RunEvalSuite
    list_runs: ListEvalRuns
    get_run: GetEvalRun
