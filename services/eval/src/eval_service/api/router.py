"""Routes of the eval service. Business logic lives in application use cases.

Who may call each route with an access token is in ``api.deps``: an admin starts a run, any
regulatory role reads them. Starting a run is synchronous: the harness's ``ci`` suites take
seconds; a nightly suite against a real model holds the request until it finishes or
``CW_EVAL_HARNESS_TIMEOUT_SECONDS`` passes.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Path, Query, status

from eval_service.api.deps import Admin, Operator, Wired
from eval_service.api.schemas import RunIn, RunOut, RunSummaryOut
from eval_service.application.queries import MAX_LIMIT, RunQuery
from eval_service.domain.model import EvalRunId, Profile, Suite
from py_common.problems import problem_responses

router = APIRouter(prefix="/v1/eval", tags=["eval"])


@router.get("/ping")
async def ping() -> dict[str, str]:
    return {"service": "eval", "status": "pong"}


@router.post(
    "/runs",
    status_code=status.HTTP_201_CREATED,
    summary="Run one harness suite under a profile and store the run with its gates and drift",
    responses=problem_responses(401, 403, 422, 502),
)
def start_run(body: RunIn, caller: Admin, wired: Wired) -> RunOut:
    """Failing gates are a result: the run is stored and ``passed`` is false. A harness that
    stops before measuring its gates is a 502 ``eval-harness-failed`` and stores nothing."""
    return RunOut.from_run(wired.run_suite.run(body.suite, body.profile))


@router.get(
    "/runs",
    summary="Stored runs, latest first, optionally of one suite or profile",
    responses=problem_responses(401, 403, 422),
)
def list_runs(
    caller: Operator,
    wired: Wired,
    suite: Annotated[Suite | None, Query(description="Only runs of this suite")] = None,
    profile: Annotated[Profile | None, Query(description="Only runs under this profile")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="At most this many runs")] = 20,
) -> list[RunSummaryOut]:
    runs = wired.list_runs.run(RunQuery(suite=suite, profile=profile, limit=limit))
    return [RunSummaryOut.from_run(run) for run in runs]


@router.get(
    "/runs/{run_id}",
    summary="One stored run with every gate and its drift against the previous run",
    responses=problem_responses(401, 403, 404, 422),
)
def get_run(
    caller: Operator,
    wired: Wired,
    run_id: Annotated[UUID, Path(description="The run's id")],
) -> RunOut:
    return RunOut.from_run(wired.get_run.run(EvalRunId(run_id)))
