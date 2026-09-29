"""The qa suite: build the world once per provider, ask every case with the KAG layer on
(``qa_kag``) and again with it off (``qa_hybrid``, the baseline), and score both runs.

Each case is asked with its ``case_id`` as the ``x-request-id``, which qa passes to every model
call as ``question_id``. An exception while asking one case is scored as no response and the run
goes on; a model call the scripted labels do not cover (``UnscriptedCallError``) stops it.
"""

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fastapi.testclient import TestClient

from cw_evals.qa.cases import QaCase, load_qa_cases
from cw_evals.qa.providers import QaModel, UnscriptedCallError, qa_model
from cw_evals.qa.score import Asked, QaAggregate, QaScore, WorldClause, aggregate, score_case
from cw_evals.qa.world import Services, WorldSpec, build_world, load_world, qa_app

ASK: Final = "/v1/qa/ask"
MODES: Final[Mapping[str, bool]] = {"qa_kag": True, "qa_hybrid": False}
"""Suite name to whether the KAG layer is on."""


@dataclass(frozen=True, slots=True)
class QaRun:
    aggregate: QaAggregate
    scores: tuple[QaScore, ...]


def load_qa_suite(golden: Path) -> tuple[WorldSpec, list[QaCase]]:
    return load_world(golden), load_qa_cases(golden)


def run_qa(
    spec: WorldSpec, cases: Sequence[QaCase], provider_name: str, *, gateway_url: str
) -> dict[str, QaRun]:
    """``qa_kag`` and ``qa_hybrid`` for one provider."""
    sources = {document.key: document.own_ref for document in spec.documents}
    runs: dict[str, QaRun] = {}
    with (
        qa_model(provider_name, cases, sources, gateway_url=gateway_url) as model,
        build_world(spec, model.client) as world,
    ):
        clauses = world_clauses(world)
        for suite, kag in MODES.items():
            with qa_app(world, kag=kag) as client:
                scores = tuple(
                    score_case(ask(client, world, model, case), clauses) for case in cases
                )
            runs[suite] = QaRun(aggregate(scores), scores)
    return runs


def world_clauses(world: Services) -> dict[tuple[str, str], WorldClause]:
    """Every clause of the world by (document id as text, clause ref)."""
    found: dict[tuple[str, str], WorldClause] = {}
    for spec in world.spec.documents:
        document_id = str(world.documents[spec.key].value)
        for clause in world.spec.cases[spec.key].document.clauses:
            found[document_id, clause.clause_ref] = WorldClause(
                spec.key, clause.clause_ref, clause.text, spec.published_on
            )
    return found


def ask(client: TestClient, world: Services, model: QaModel, case: QaCase) -> Asked:
    body: dict[str, Any] = {"question": case.question, "as_of": case.as_of.isoformat()}
    if case.business is not None:
        body["business_node_id"] = str(world.businesses[case.business].value)
    if case.fy is not None:
        body["fy"] = case.fy
    headers = {
        "x-tenant-id": str(world.tenant_for(case.business).value),
        "x-request-id": case.case_id,
    }
    model.start(case.case_id)
    before = len(model.log.calls)
    started = time.perf_counter()
    status: int | None = None
    answer: Any = None
    error = ""
    try:
        response = client.post(ASK, json=body, headers=headers)
        status = response.status_code
        answer = response.json()
    except UnscriptedCallError:
        raise
    except Exception as exc:  # one failing question is scored, not fatal
        error = f"{type(exc).__name__}: {exc}"
    if model.aborted is not None:
        raise model.aborted
    return Asked(
        case=case,
        status=status,
        body=answer if isinstance(answer, dict) else None,
        error=error or ("" if status == 200 else f"HTTP {status}: {str(answer)[:300]}"),
        calls=tuple(model.log.calls[before:]),
        latency_ms=(time.perf_counter() - started) * 1000,
    )
