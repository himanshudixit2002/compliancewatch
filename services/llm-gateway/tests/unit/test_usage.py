"""GET /v1/llm-gateway/usage: one monthly budget, read back from the ledger."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

COMPLETIONS = "/v1/llm-gateway/completions"
USAGE = "/v1/llm-gateway/usage"
PREFIX = "urn:compliancewatch:problem:"
PROBLEM = "application/problem+json"


def _call(client: TestClient, user: str, tenant: str | None = None) -> Decimal:
    body: dict[str, Any] = {"feature": "smoke", "prompt": "smoke.echo@1", "user": user}
    headers = {} if tenant is None else {"x-tenant-id": tenant}
    response = client.post(COMPLETIONS, json=body, headers=headers)
    assert response.status_code == 200
    return Decimal(response.json()["cost_inr"])


def _this_month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _next_month_start() -> str:
    now = datetime.now(UTC)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{year:04d}-{month:02d}-01T00:00:00Z"


def test_tenant_scope_sums_the_tenant_calls(client: TestClient) -> None:
    tenant = str(uuid4())
    spent = _call(client, "first " * 40, tenant) + _call(client, "second " * 40, tenant)
    assert spent > 0

    response = client.get(USAGE, headers={"x-tenant-id": tenant})
    assert response.status_code == 200
    assert response.json() == {
        "scope": "tenant",
        "key": tenant,
        "month": _this_month(),
        "spent_inr": format(spent, "f"),
        "budget_inr": "1500",
        "ratio": format((spent / Decimal("1500")).quantize(Decimal("0.000001")), "f"),
        "alarmed": False,
        "resets_at": _next_month_start(),
    }


def test_other_tenants_do_not_count(client: TestClient) -> None:
    tenant, other = str(uuid4()), str(uuid4())
    _call(client, "mine " * 40, tenant)
    _call(client, "theirs " * 40, other)
    response = client.get(USAGE, headers={"x-tenant-id": other})
    assert response.json()["key"] == other
    assert Decimal(response.json()["spent_inr"]) == _call(client, "theirs " * 40 + "x", other)


def test_tenant_query_parameter_beats_the_header(client: TestClient) -> None:
    header_tenant, query_tenant = str(uuid4()), str(uuid4())
    _call(client, "hello " * 40, header_tenant)
    response = client.get(
        USAGE, params={"tenant_id": query_tenant}, headers={"x-tenant-id": header_tenant}
    )
    assert response.status_code == 200
    assert response.json()["key"] == query_tenant
    assert response.json()["spent_inr"] == "0.0000"


def test_feature_scope_without_a_tenant(client: TestClient) -> None:
    spent = _call(client, "hello " * 40) + _call(client, "hello " * 40, str(uuid4()))
    response = client.get(USAGE, params={"feature": "smoke"})
    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "feature"
    assert body["key"] == "smoke"
    assert body["spent_inr"] == format(spent, "f")
    assert body["budget_inr"] == "20000"
    assert body["alarmed"] is False


def test_feature_narrows_a_tenant_sum(client: TestClient) -> None:
    tenant = str(uuid4())
    spent = _call(client, "hello " * 40, tenant)
    on_smoke = client.get(USAGE, params={"feature": "smoke"}, headers={"x-tenant-id": tenant})
    on_qa = client.get(USAGE, params={"feature": "qa"}, headers={"x-tenant-id": tenant})
    assert on_smoke.json()["scope"] == "tenant"
    assert Decimal(on_smoke.json()["spent_inr"]) == spent
    assert on_qa.json()["scope"] == "tenant"
    assert on_qa.json()["spent_inr"] == "0.0000"
    assert on_qa.json()["budget_inr"] == "1500"


def test_another_month_is_empty(client: TestClient) -> None:
    _call(client, "hello " * 40)
    response = client.get(USAGE, params={"feature": "smoke", "month": "2020-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["month"] == "2020-01"
    assert body["spent_inr"] == "0.0000"
    assert body["ratio"] == "0.000000"
    assert body["resets_at"] == "2020-02-01T00:00:00Z"


def test_december_resets_in_january(client: TestClient) -> None:
    response = client.get(USAGE, params={"feature": "smoke", "month": "2025-12"})
    assert response.json()["resets_at"] == "2026-01-01T00:00:00Z"


def test_bad_month_is_a_422_problem(client: TestClient) -> None:
    for month in ("2026-13", "2026-1", "202609", "2026-09-01"):
        response = client.get(USAGE, params={"feature": "smoke", "month": month})
        assert response.status_code == 422, month
        assert response.headers["content-type"].startswith(PROBLEM)
        assert response.json()["type"] == PREFIX + "request-invalid"
        assert response.json()["errors"][0]["loc"] == ["query", "month"]


def test_unknown_feature_is_a_422_problem(client: TestClient) -> None:
    response = client.get(USAGE, params={"feature": "billing"})
    assert response.status_code == 422
    assert response.json()["errors"][0]["loc"] == ["query", "feature"]


def test_neither_tenant_nor_feature_is_a_422_problem(client: TestClient) -> None:
    response = client.get(USAGE)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM)
    problem = response.json()
    assert problem["type"] == PREFIX + "invariant-violation"
    assert problem["detail"] == "usage needs a tenant_id or a feature"
    assert problem["instance"] == USAGE


def test_alarm_shows_once_spend_crosses_the_ratio(client: TestClient) -> None:
    tenant = str(uuid4())
    before = client.get(USAGE, headers={"x-tenant-id": tenant}).json()
    assert before["spent_inr"] == "0.0000"
    assert before["alarmed"] is False
    assert before["ratio"] == "0.000000"
