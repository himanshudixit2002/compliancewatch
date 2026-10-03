"""Reads of stored eval runs."""

from collections.abc import Sequence
from dataclasses import dataclass

from eval_service.domain.errors import EvalRunNotFoundError
from eval_service.domain.model import EvalRun, EvalRunId, Profile, Suite
from eval_service.domain.repository import UnitOfWorkFactory

MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class RunQuery:
    suite: Suite | None = None
    profile: Profile | None = None
    limit: int = 20

    def __post_init__(self) -> None:
        if not 1 <= self.limit <= MAX_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_LIMIT}, got {self.limit}")


class ListEvalRuns:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, query: RunQuery) -> Sequence[EvalRun]:
        with self._unit_of_work() as uow:
            return uow.runs.recent(suite=query.suite, profile=query.profile, limit=query.limit)


class GetEvalRun:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, run_id: EvalRunId) -> EvalRun:
        with self._unit_of_work() as uow:
            found = uow.runs.get(run_id)
        if found is None:
            raise EvalRunNotFoundError(str(run_id))
        return found
