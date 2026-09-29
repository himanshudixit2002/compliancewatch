"""POST /v1/qa/ask: the answer shape, the layers, the plan, the problems, and the request id
reaching every model call."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from domain_kernel.errors import PROBLEM_TYPE_PREFIX
from qa.domain.answer import NOT_COVERED_TEXT
from qa.domain.errors import GatewayError
from qa.infrastructure.prompts import PROMPTS_DIR
from qa.main import build_app, wire
from qa.testing import answer_text, plan_step, plan_text, qa_settings

World = Any
ASK = "/v1/qa/ask"


@contextmanager
def api(world: World, **settings: Any) -> Iterator[TestClient]:
    app = build_app(qa_settings(**settings), ports=world.ports(), ontology=world.ontology)
    with TestClient(app) as client:
        yield client


def headers(world: World, request_id: str | None = None) -> dict[str, str]:
    found = {"x-tenant-id": str(world.TENANT)}
    if request_id is not None:
        found["x-request-id"] = request_id
    return found


def body(world: World, question: str, **fields: Any) -> dict[str, Any]:
    return {
        "question": question,
        "as_of": "2026-04-10",
        "business_node_id": str(world.BUSINESS.value),
        **fields,
    }


def problem_type(response: Any) -> str:
    assert response.headers["content-type"] == "application/problem+json"
    kind: str = response.json()["type"]
    return kind.removeprefix(PROBLEM_TYPE_PREFIX)


def test_a_structured_answer(world: World) -> None:
    with api(world) as client:
        response = client.post(
            ASK, json=body(world, "What is due next month?"), headers=headers(world)
        )
    assert response.status_code == 200
    clause = world.monthly_clause
    assert response.json() == {
        "outcome": "answered",
        "answer": "Due next month: File GSTR-3B for the month (2026-04), due on 20 May 2026.",
        "citations": [
            {
                "clause_ref": "en.p1",
                "document_id": str(clause.document_id),
                "quote": world.MONTHLY_QUOTE,
            }
        ],
        "layer": "structured",
        "layers": [{"layer": "structured", "result": "answered", "reason": None}],
        "plan": None,
        "reason": None,
        "as_of": "2026-04-10",
    }


def test_a_kag_answer_carries_the_plan_and_the_request_id(world: World) -> None:
    plan = plan_text(
        plan_step(1, "rules_in_force", rule_key=world.MONTHLY_RULE),
        plan_step(
            2, "follow", source="s1", relations=["extends_deadline"], direction="in", depth=1
        ),
        plan_step(3, "answer", sources=["s2"]),
    )
    world.provider.add("case-7", world.PLAN, plan)
    world.provider.add(
        "case-7", world.ANSWER, answer_text("24 April 2026.", ("C1", world.EXTENSION_QUOTE))
    )
    question = "Which notice extended the March 2026 GSTR-3B?"
    with api(world, qa_kag_enabled=True) as client:
        response = client.post(ASK, json=body(world, question), headers=headers(world, "case-7"))
    assert response.status_code == 200
    answer = response.json()
    assert (answer["outcome"], answer["layer"], answer["answer"]) == (
        "answered",
        "kag",
        "24 April 2026.",
    )
    assert answer["layers"] == [
        {"layer": "structured", "result": "passed", "reason": None},
        {"layer": "kag", "result": "answered", "reason": None},
    ]
    assert [step["op"] for step in answer["plan"]["steps"]] == [
        "rules_in_force",
        "follow",
        "answer",
    ]
    assert answer["plan"]["steps"][1]["relations"] == ["extends_deadline"]
    assert answer["citations"][0]["clause_ref"] == "en.p3"
    assert [dict(req.metadata) for req in world.provider.requests] == [
        {"question_id": "case-7", "stage": "plan", "attempt": "1", "layer": "kag"},
        {"question_id": "case-7", "stage": "answer", "attempt": "1", "layer": "kag"},
    ]
    assert response.headers["x-request-id"] == "case-7"


def test_a_tenant_outside_the_list_gets_hybrid(world: World) -> None:
    world.provider.add("r1", world.ANSWER, answer_text("", covered=False))
    other = str(world.OTHER_TENANT)
    question = "Which notice extended the March 2026 GSTR-3B?"
    with api(world, qa_kag_enabled=True, qa_kag_tenants=other) as client:
        response = client.post(ASK, json=body(world, question), headers=headers(world, "r1"))
    answer = response.json()
    assert (answer["outcome"], answer["answer"], answer["reason"]) == (
        "not_covered",
        NOT_COVERED_TEXT,
        "answerer_declined",
    )
    assert [layer["layer"] for layer in answer["layers"]] == ["structured", "hybrid"]
    assert world.provider.calls(world.PLAN) == []


def test_not_covered_without_evidence(world: World) -> None:
    with api(world) as client:
        response = client.post(
            ASK, json={"question": "What is the rate on cement?"}, headers=headers(world)
        )
    answer = response.json()
    assert (answer["outcome"], answer["reason"], answer["layers"][-1]) == (
        "not_covered",
        "no_evidence",
        {"layer": "hybrid", "result": "not_covered", "reason": "no_evidence"},
    )


def test_the_date_defaults_to_today_in_india(world: World) -> None:
    app = build_app(qa_settings(), ports=world.ports(), ontology=world.ontology)
    app.state.wiring = replace(app.state.wiring, today=lambda: date(2026, 4, 10))
    with TestClient(app) as client:
        response = client.post(
            ASK,
            json={"question": "What is due next month?", "business_node_id": str(world.BUSINESS)},
            headers=headers(world),
        )
    assert (response.json()["as_of"], response.json()["layer"]) == ("2026-04-10", "structured")
    assert wire(qa_settings()).today() >= date(2026, 1, 1)


def test_a_tenant_is_required(world: World) -> None:
    with api(world) as client:
        response = client.post(ASK, json=body(world, "When is my GSTR-3B due?"))
    assert response.status_code == 401
    assert problem_type(response) == "qa-tenant-required"


def test_an_unknown_business_is_404(world: World) -> None:
    unknown = body(world, "When is my GSTR-3B due?", business_node_id=str(world.OTHER_TENANT))
    with api(world) as client:
        response = client.post(ASK, json=unknown, headers=headers(world))
    assert response.status_code == 404
    assert problem_type(response) == "qa-business-not-found"


def test_invalid_requests_are_422(world: World) -> None:
    with api(world) as client:
        blank = client.post(ASK, json=body(world, "   "), headers=headers(world))
        extra = client.post(ASK, json=body(world, "why", topic="x"), headers=headers(world))
        pattern = client.post(ASK, json=body(world, "why", fy="2025"), headers=headers(world))
        years = client.post(ASK, json=body(world, "why", fy="2025-27"), headers=headers(world))
    assert [r.status_code for r in (blank, extra, pattern, years)] == [422, 422, 422, 422]
    assert problem_type(blank) == "request-invalid"
    assert problem_type(years) == "qa-question-invalid"


def test_an_upstream_outage_is_503(world: World) -> None:
    world.rulebook.fail = True
    with api(world) as client:
        response = client.post(
            ASK, json=body(world, "When is my GSTR-3B due?"), headers=headers(world)
        )
    assert response.status_code == 503
    assert problem_type(response) == "qa-dependency-unavailable"


def test_a_gateway_outage_while_answering_is_503(world: World) -> None:
    world.provider.add("r2", world.ANSWER, GatewayError("502: provider down"))
    with api(world) as client:
        response = client.post(
            ASK, json={"question": "GSTR-3B March"}, headers=headers(world, "r2")
        )
    assert response.status_code == 503
    assert "llm-gateway: 502" in response.json()["detail"]


def test_readiness_reads_the_prompts_again(world: World, tmp_path: Path) -> None:
    for name in ("qa.plan.v1.md", "qa.answer.v1.md"):
        shutil.copy(PROMPTS_DIR / name, tmp_path / name)
    with api(world, qa_prompts_dir=tmp_path) as client:
        assert client.get("/ready").json() == {"status": "ready", "checks": {"prompts": True}}
        (tmp_path / "qa.plan.v1.md").unlink()
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"prompts": False}
