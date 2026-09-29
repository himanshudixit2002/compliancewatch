"""The HTTP surface on the memory store: registration, attributes, snapshot, next question,
review tasks, the financial year confirmation and the problem responses; and the command that
runs the confirmation for named tenants."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ontology as ontology_package
from domain_kernel.financial_year import FinancialYear
from profile_service import jobs
from profile_service.api.deps import clock
from profile_service.application.attributes import ConfirmFinancialYear
from profile_service.application.registration import RegisterNodes
from profile_service.infrastructure.memory import MemoryStore
from profile_service.testing import GSTIN_KARNATAKA, OTHER_TENANT, PAN, TENANT

HEADERS = {"x-tenant-id": str(TENANT)}
CONFIRMATIONS = "/v1/profile/financial-year-confirmations"
LAST_EVENING_OF_MARCH_IST = datetime(2027, 3, 31, 18, 29, tzinfo=UTC)
"""23:59 IST on 31 March 2027: still financial year 2026-27."""
FIRST_MINUTE_OF_APRIL_IST = datetime(2027, 3, 31, 18, 30, tzinfo=UTC)
"""00:00 IST on 1 April 2027, still 31 March in UTC: financial year 2027-28."""


def register(client: TestClient) -> tuple[str, str]:
    response = client.post(
        "/v1/profile/registrations",
        json={"gstin": "29abcde1234f1z5", "name": "Acme Bengaluru", "entity_name": "Acme"},
        headers=HEADERS,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["created"] is True
    assert body["level"] == "registration"
    assert body["key"] == GSTIN_KARNATAKA.value
    return body["parent_id"], body["id"]


def test_registration_creates_the_entity_and_is_idempotent(client: TestClient) -> None:
    entity_id, registration_id = register(client)
    entity = client.get(f"/v1/profile/nodes/{entity_id}", headers=HEADERS).json()
    assert (entity["level"], entity["key"], entity["name"]) == ("entity", PAN.value, "Acme")
    again = client.post(
        "/v1/profile/registrations",
        json={"gstin": GSTIN_KARNATAKA.value, "name": "x"},
        headers=HEADERS,
    )
    assert again.status_code == 201
    assert again.json()["created"] is False
    assert again.json()["id"] == registration_id
    entity_again = client.post(
        "/v1/profile/entities", json={"pan": " abcde1234f ", "name": "Acme"}, headers=HEADERS
    )
    assert entity_again.json()["created"] is False
    location = client.post(
        "/v1/profile/locations",
        json={"registration_id": registration_id, "label": "whitefield", "name": "Whitefield"},
        headers=HEADERS,
    )
    assert location.status_code == 201
    assert location.json()["parent_id"] == registration_id


def test_attributes_snapshot_next_question_and_review_tasks(client: TestClient) -> None:
    entity_id, registration_id = register(client)
    response = client.put(
        f"/v1/profile/nodes/{entity_id}/attributes",
        json={
            "changes": [
                {"key": "turnover_band", "value": "2_crore_to_5_crore", "as_of_fy": "2025-26"},
                {"key": "state_codes", "value": ["29"], "source": "gstin_lookup"},
                {"key": "employee_count", "state": "not_applicable"},
                {"key": "constitution", "state": "unsure"},
            ],
            "source": "user_input",
            "changed_by": str(uuid4()),
        },
        headers=HEADERS,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] == ["turnover_band", "state_codes", "employee_count", "constitution"]
    assert body["node"]["version"] == 2
    assert len(body["review_tasks"]) == 1
    stored = {item["key"]: item for item in body["node"]["attributes"]}
    assert stored["state_codes"]["value"] == ["29"]
    assert stored["turnover_band"]["as_of_fy"] == "2025-26"
    assert stored["employee_count"]["state"] == "not_applicable"

    client.put(
        f"/v1/profile/nodes/{registration_id}/attributes",
        json={
            "changes": [{"key": "registration_type", "value": "regular"}],
            "source": "gstin_lookup",
        },
        headers=HEADERS,
    )
    snapshot = client.get(
        f"/v1/profile/nodes/{registration_id}/snapshot", params={"fy": "2025-26"}, headers=HEADERS
    ).json()
    assert snapshot["attributes"] == {
        "turnover_band": "2_crore_to_5_crore",
        "state_codes": ["29"],
        "registration_type": "regular",
    }
    assert snapshot["lineage"] == [entity_id]
    assert snapshot["level"] == "registration"
    no_year = client.get(f"/v1/profile/nodes/{registration_id}/snapshot", headers=HEADERS).json()
    assert "turnover_band" not in no_year["attributes"]

    question = client.get(
        f"/v1/profile/nodes/{entity_id}/next-question", params={"fy": "2025-26"}, headers=HEADERS
    ).json()
    assert question["attribute"] == "constitution"
    assert question["type"] == "enum"
    assert "proprietorship" in question["allowed_values"]

    tasks = client.get(f"/v1/profile/nodes/{entity_id}/review-tasks", headers=HEADERS).json()
    assert [(t["attribute_key"], t["reason"], t["open"]) for t in tasks] == [
        ("employee_count", "not_applicable", True)
    ]


def test_problem_responses(client: TestClient) -> None:
    missing_tenant = client.post("/v1/profile/entities", json={"pan": "ABCDE1234F", "name": "x"})
    assert missing_tenant.status_code == 401
    assert missing_tenant.headers["content-type"].startswith("application/problem+json")
    assert missing_tenant.json()["type"].endswith("tenant-required")

    unknown = client.get(f"/v1/profile/nodes/{uuid4()}", headers=HEADERS)
    assert unknown.status_code == 404
    assert unknown.json()["type"].endswith("profile-node-not-found")

    entity_id, registration_id = register(client)
    wrong_level = client.put(
        f"/v1/profile/nodes/{entity_id}/attributes",
        json={"changes": [{"key": "registration_type", "value": "regular"}]},
        headers=HEADERS,
    )
    assert wrong_level.status_code == 422
    assert wrong_level.json()["type"].endswith("profile-attribute-level-mismatch")

    no_year = client.put(
        f"/v1/profile/nodes/{entity_id}/attributes",
        json={"changes": [{"key": "turnover_band", "value": "upto_10_lakh"}]},
        headers=HEADERS,
    )
    assert no_year.status_code == 422
    assert no_year.json()["type"].endswith("profile-financial-year-required")

    bad_value = client.put(
        f"/v1/profile/nodes/{registration_id}/attributes",
        json={"changes": [{"key": "registration_type", "value": "nonsense"}]},
        headers=HEADERS,
    )
    assert bad_value.status_code == 422

    bad_gstin = client.post(
        "/v1/profile/registrations",
        json={"gstin": "29ZZZZZ9999Z1Z5X", "name": "x"},
        headers=HEADERS,
    )
    assert bad_gstin.status_code == 422

    bad_body = client.post("/v1/profile/entities", json={"pan": "ABCDE1234F"}, headers=HEADERS)
    assert bad_body.status_code == 422
    assert bad_body.json()["errors"][0]["loc"] == ["body", "name"]

    bad_tenant = client.get("/v1/profile/ping", headers={"x-tenant-id": "nope"})
    assert bad_tenant.status_code == 200, "ping does not read the tenant"
    assert (
        client.get(f"/v1/profile/nodes/{uuid4()}", headers={"x-tenant-id": "nope"}).status_code
        == 422
    )


def test_the_default_financial_year_comes_from_the_clock_in_ist(
    app: FastAPI, client: TestClient
) -> None:
    register(client)
    app.dependency_overrides[clock] = lambda: LAST_EVENING_OF_MARCH_IST
    march = client.post(CONFIRMATIONS, headers=HEADERS)
    assert march.status_code == 200, march.text
    assert march.json()["fy"] == "2026-27"
    app.dependency_overrides[clock] = lambda: FIRST_MINUTE_OF_APRIL_IST
    april = client.post(CONFIRMATIONS, json={}, headers=HEADERS)
    assert april.json()["fy"] == "2027-28"
    assert len(april.json()["opened"]) == len(march.json()["opened"]) >= 1


def test_an_explicit_financial_year_opens_its_tasks_once(client: TestClient) -> None:
    entity_id, _ = register(client)
    first = client.post(CONFIRMATIONS, json={"fy": "2026-27"}, headers=HEADERS)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["fy"] == "2026-27"
    assert body["opened"]
    tasks = client.get(f"/v1/profile/nodes/{entity_id}/review-tasks", headers=HEADERS).json()
    confirmations = [t for t in tasks if t["reason"] == "confirm_financial_year"]
    assert {t["id"] for t in confirmations} == set(body["opened"])
    assert {t["as_of_fy"] for t in confirmations} == {"2026-27"}
    again = client.post(CONFIRMATIONS, json={"fy": "2026-27"}, headers=HEADERS)
    assert again.json() == {"fy": "2026-27", "opened": []}
    other = client.post(
        CONFIRMATIONS, json={"fy": "2026-27"}, headers={"x-tenant-id": str(OTHER_TENANT)}
    )
    assert other.json() == {"fy": "2026-27", "opened": []}


@pytest.mark.parametrize("fy", ["2026", "2026-2027", "26-27", "2026-28", "2026-26"])
def test_a_malformed_financial_year_is_422(client: TestClient, fy: str) -> None:
    response = client.post(CONFIRMATIONS, json={"fy": fy}, headers=HEADERS)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


def test_the_confirmation_needs_a_tenant(client: TestClient) -> None:
    response = client.post(CONFIRMATIONS, json={"fy": "2026-27"})
    assert response.status_code == 401
    assert response.json()["type"].endswith("tenant-required")


def test_the_command_prints_the_counts_per_tenant(capsys: pytest.CaptureFixture[str]) -> None:
    store = MemoryStore()
    RegisterNodes(store).entity(TENANT, PAN, "Acme")
    confirm = ConfirmFinancialYear(store, ontology_package.load())
    tenants = ["--tenant", str(TENANT), "--tenant", str(OTHER_TENANT), "--tenant", str(TENANT)]
    assert jobs.main([*tenants, "--fy", "2026-27"], confirm=confirm) == 0
    lines = capsys.readouterr().out.splitlines()
    opened = len(confirm.run(TENANT, FinancialYear(2030)))
    assert opened >= 1
    assert lines == [
        f"{TENANT}: {opened} task(s) opened for 2026-27",
        f"{OTHER_TENANT}: 0 task(s) opened for 2026-27",
        f"financial year 2026-27: {opened} task(s) opened for 2 tenant(s)",
    ]
    assert jobs.main(tenants[:2], confirm=confirm, clock=lambda: FIRST_MINUTE_OF_APRIL_IST) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"financial year 2027-28: {opened} task(s) opened for 1 tenant(s)"
    )


def test_the_command_on_the_memory_store_and_its_argument_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CW_PROFILE_STORE", "memory")
    assert jobs.main(["--tenant", str(TENANT), "--fy", "2026-27"]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "financial year 2026-27: 0 task(s) opened for 1 tenant(s)"
    )
    for argv in ([], ["--tenant", "nope"], ["--tenant", str(TENANT), "--fy", "2026-28"]):
        with pytest.raises(SystemExit) as exited:
            jobs.main(argv)
        assert exited.value.code == 2
    assert "not a tenant UUID" in capsys.readouterr().err
