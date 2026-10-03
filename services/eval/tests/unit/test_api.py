"""The eval routes over the memory store and a scripted runner, in header mode (no token)."""

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from eval_service.main import build_app
from eval_service.testing import ScriptedRunner, eval_settings, gate

RUNS = "/v1/eval/runs"
RECALL = "relations.relation_recall[scripted]"
PARSE = "relations.relation_parse_rate[fake]"


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def start(client: TestClient, suite: str = "relations", profile: str = "ci") -> Any:
    return client.post(RUNS, json={"suite": suite, "profile": profile})


@pytest.fixture
def scripted() -> ScriptedRunner:
    return ScriptedRunner(
        [gate(RECALL, 1.0), gate(PARSE, 1.0)], [gate(RECALL, 0.5), gate(PARSE, 1.0)]
    )


@pytest.fixture
def drifting(scripted: ScriptedRunner) -> TestClient:
    return TestClient(build_app(eval_settings(), runner=scripted))


def test_starting_a_run_stores_it_with_its_gates(drifting: TestClient) -> None:
    response = start(drifting)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["suite"] == "relations"
    assert body["profile"] == "ci"
    assert body["passed"] is True
    assert body["gates_total"] == 2
    assert body["previous_run_id"] is None
    assert body["gates"][0] == {
        "name": RECALL,
        "metric": "relation_recall",
        "threshold": 1.0,
        "value": 1.0,
        "passed": True,
        "previous_value": None,
        "drift": None,
    }
    stored = drifting.get(f"{RUNS}/{body['run_id']}")
    assert stored.status_code == 200
    assert stored.json() == body


def test_a_second_run_reports_drift_and_failed_gates(drifting: TestClient) -> None:
    first = start(drifting).json()
    second = start(drifting).json()
    assert second["previous_run_id"] == first["run_id"]
    assert second["passed"] is False
    assert second["failed_gates"] == [RECALL]
    assert second["regressed_gates"] == [RECALL]
    recall = second["gates"][0]
    assert (recall["value"], recall["previous_value"], recall["drift"]) == (0.5, 1.0, -0.5)


def test_the_profile_defaults_to_ci(client: TestClient, runner: ScriptedRunner) -> None:
    assert client.post(RUNS, json={"suite": "qa"}).status_code == 201
    assert runner.calls[-1][1].value == "ci"


def test_listing_runs_without_their_gates(drifting: TestClient) -> None:
    first = start(drifting).json()
    second = start(drifting).json()
    start(drifting, suite="qa", profile="nightly")
    listed = drifting.get(RUNS, params={"suite": "relations"})
    assert listed.status_code == 200
    assert [run["run_id"] for run in listed.json()] == [second["run_id"], first["run_id"]]
    assert "gates" not in listed.json()[0]
    assert len(drifting.get(RUNS, params={"profile": "nightly"}).json()) == 1
    assert len(drifting.get(RUNS, params={"limit": 1}).json()) == 1


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 101}, {"suite": "unknown"}, {"profile": "weekly"}]
)
def test_listing_refuses_bad_filters(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get(RUNS, params=params).status_code == 422


@pytest.mark.parametrize(
    "body",
    [{}, {"suite": "unknown"}, {"suite": "qa", "profile": "weekly"}, {"suite": "qa", "x": 1}],
)
def test_starting_refuses_a_bad_body(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post(RUNS, json=body).status_code == 422


def test_an_unknown_run_is_a_404(client: TestClient) -> None:
    response = client.get(f"{RUNS}/{uuid4()}")
    assert (response.status_code, problem(response)) == (404, "eval-run-not-found")


def test_a_harness_failure_is_a_502_and_stores_nothing() -> None:
    failing = TestClient(build_app(eval_settings(), runner=ScriptedRunner(failure="aborted")))
    response = start(failing)
    assert (response.status_code, problem(response)) == (502, "eval-harness-failed")
    assert response.json()["detail"] == "aborted"
    assert failing.get(RUNS).json() == []
