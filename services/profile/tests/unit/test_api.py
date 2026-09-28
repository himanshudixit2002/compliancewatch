"""The HTTP surface on the memory store: registration, attributes, snapshot, next question,
review tasks, and the problem responses."""

from uuid import uuid4

from fastapi.testclient import TestClient

from profile_service.testing import GSTIN_KARNATAKA, PAN, TENANT

HEADERS = {"x-tenant-id": str(TENANT)}


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
