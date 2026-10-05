"""The obligation read route on the memory store: the tenant header, the window and the body."""

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient

from domain_kernel.ids import RuleVersionId
from obligation.application.materialise import MaterialiseRequest
from obligation.testing import BUSINESS, DECISION, OTHER_TENANT, TENANT, rule

ROUTE = "/v1/obligation/obligations"
FIELDS = {
    "obligation_id",
    "business_id",
    "rule_version_id",
    "decision_id",
    "title",
    "steps",
    "evidence_type",
    "period_label",
    "period_start",
    "period_end",
    "due_at",
    "status",
    "closed_at",
    "closed_reason",
    "profile_version",
    "assignee_id",
}


def headers(tenant: object = TENANT) -> dict[str, str]:
    return {"x-tenant-id": str(tenant)}


def seed(app: FastAPI) -> None:
    app.state.wiring.materialise.run(
        MaterialiseRequest(TENANT, BUSINESS, DECISION, rule(), date(2026, 9, 28))
    )


def test_obligations_of_a_business_in_a_window(app: FastAPI, client: TestClient) -> None:
    seed(app)
    response = client.get(ROUTE, params={"business_id": str(BUSINESS)}, headers=headers())
    assert response.status_code == 200
    body = response.json()
    assert [item["period_label"] for item in body] == ["2026-09", "2026-10"]
    first = body[0]
    assert set(first) == FIELDS
    assert first["business_id"] == str(BUSINESS)
    assert first["title"] == "File GSTR-3B (2026-09)"
    assert first["steps"] == ["Reconcile", "File"]
    assert first["evidence_type"] == "filing_acknowledgement"
    assert (first["period_start"], first["period_end"]) == ("2026-09-01", "2026-10-01")
    assert first["due_at"] == "2026-10-20T18:29:59Z"
    assert (first["status"], first["closed_at"], first["closed_reason"]) == ("open", None, None)
    assert (first["profile_version"], first["assignee_id"]) == (None, None)

    october = client.get(
        ROUTE,
        params={"business_id": str(BUSINESS), "due_from": "2026-11-01", "due_to": "2026-11-30"},
        headers=headers(),
    )
    assert [item["period_label"] for item in october.json()] == ["2026-10"]
    other_version = client.get(
        ROUTE,
        params={"business_id": str(BUSINESS), "rule_version_id": str(RuleVersionId.new())},
        headers=headers(),
    )
    assert other_version.json() == []


def test_another_tenant_sees_nothing(app: FastAPI, client: TestClient) -> None:
    seed(app)
    response = client.get(
        ROUTE, params={"business_id": str(BUSINESS)}, headers=headers(OTHER_TENANT)
    )
    assert response.status_code == 200
    assert response.json() == []


def test_the_tenant_header_is_required(client: TestClient) -> None:
    response = client.get(ROUTE, params={"business_id": str(BUSINESS)})
    assert response.status_code == 401
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["type"].endswith(":obligation-tenant-required")
    assert problem["title"] == "Tenant required for obligations"


def test_an_invalid_window_is_a_422_problem(client: TestClient) -> None:
    for due_from, due_to in (("2026-11-01", "2026-10-31"), ("2026-04-01", "2027-04-02")):
        response = client.get(
            ROUTE,
            params={"business_id": str(BUSINESS), "due_from": due_from, "due_to": due_to},
            headers=headers(),
        )
        assert response.status_code == 422
        assert response.json()["type"].endswith(":obligation-window-invalid")


def test_a_window_ending_on_the_last_date_is_a_422_problem(client: TestClient) -> None:
    """The window's upper bound is the start of the day after ``due_to``, which does not exist
    for the last date there is."""
    for window in ({"due_to": "9999-12-31"}, {"due_from": "9999-12-01", "due_to": "9999-12-31"}):
        response = client.get(
            ROUTE, params={"business_id": str(BUSINESS), **window}, headers=headers()
        )
        assert response.status_code == 422
        assert response.json()["type"].endswith(":obligation-window-invalid")


def test_the_business_is_required(client: TestClient) -> None:
    response = client.get(ROUTE, headers=headers())
    assert response.status_code == 422
    assert response.json()["type"].endswith(":request-invalid")
