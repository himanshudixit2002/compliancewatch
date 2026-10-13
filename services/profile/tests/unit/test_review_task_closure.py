"""Review tasks close: an answer to the attribute a task asks about closes it in the same unit
of work, a person resolves one through the route, both audited; the open list and the snapshot
show the change; the financial year confirmation never reopens a task; and the attribute usage
and tenant directory twins count across tenants."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ontology as ontology_package
from domain_kernel.access import Role
from domain_kernel.financial_year import FinancialYear
from domain_kernel.identifiers import Pan
from domain_kernel.ids import BusinessId, TenantId
from domain_kernel.ontology import Ontology
from profile_service.application.attributes import ConfirmFinancialYear, SetAttributes
from profile_service.application.audit import REVIEW_TASK_CLOSED
from profile_service.application.registration import RegisterNodes
from profile_service.application.review_tasks import ResolveReviewTask
from profile_service.domain.errors import (
    ProfileNodeNotFoundError,
    ReviewTaskClosedError,
    ReviewTaskNotFoundError,
)
from profile_service.domain.events import ChangeSource
from profile_service.domain.model import (
    AttributeChange,
    AttributeUsage,
    ReviewClosedBy,
    ReviewOutcome,
    ReviewReason,
    ReviewTask,
    ValueState,
)
from profile_service.infrastructure.memory import (
    MemoryAttributeUsage,
    MemoryStore,
    MemoryTenantDirectory,
)
from profile_service.main import build_app
from profile_service.settings import ProfileSettings
from profile_service.testing import OTHER_TENANT, PAN, TENANT, clock
from py_common.auth.testing import TestIssuer, bearer

AT = datetime(2000, 6, 1, 9, 0, tzinfo=UTC)
FY = FinancialYear(2000)
HEADERS = {"x-tenant-id": str(TENANT)}


def settings(**overrides: Any) -> ProfileSettings:
    """Settings that ignore the repo ``.env``; the memory store unless told otherwise."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "profile",
        "profile_store": "memory",
    }
    values.update(overrides)
    return ProfileSettings(**values)


@pytest.fixture(scope="module")
def ontology() -> Ontology:
    return ontology_package.load()


def entity(store: MemoryStore, tenant: TenantId = TENANT, pan: Pan = PAN) -> BusinessId:
    return RegisterNodes(store, clock=clock).entity(tenant, pan, "Example Traders").node.id


def answer(
    store: MemoryStore,
    ontology: Ontology,
    node: BusinessId,
    *changes: AttributeChange,
    tenant: TenantId = TENANT,
) -> Any:
    return SetAttributes(store, ontology, clock=clock).run(
        tenant, node, list(changes), source=ChangeSource.USER_INPUT
    )


def closed_entries(store: MemoryStore) -> list[Any]:
    return [entry for entry in store.audit if entry.action == REVIEW_TASK_CLOSED]


# ---------------------------------------------------------------- the model


def test_a_task_closes_once_by_an_answer_or_a_resolve() -> None:
    task = ReviewTask(
        id=BusinessId.new(),
        tenant_id=TENANT,
        node_id=BusinessId.new(),
        attribute_key="turnover_band",
        reason=ReviewReason.CONFIRM_FINANCIAL_YEAR,
        as_of_fy=FY,
        open=True,
        created_at=AT,
    )
    assert task.storage_key == ("turnover_band", "2000-01")
    answered = task.answered(AT)
    assert (answered.open, answered.closed_by, answered.outcome, answered.closed_at) == (
        False,
        ReviewClosedBy.ANSWER,
        ReviewOutcome.ANSWERED,
        AT,
    )
    resolved = task.resolved(ReviewOutcome.DISMISSED, "  Example: checked by hand  ", AT)
    assert (resolved.closed_by, resolved.outcome, resolved.note) == (
        ReviewClosedBy.RESOLVE,
        ReviewOutcome.DISMISSED,
        "Example: checked by hand",
    )
    with pytest.raises(ReviewTaskClosedError):
        answered.resolved(ReviewOutcome.CONFIRMED, "", AT)
    with pytest.raises(ReviewTaskClosedError):
        resolved.answered(AT)
    with pytest.raises(ValueError, match="confirmed or dismissed"):
        task.resolved(ReviewOutcome.ANSWERED, "", AT)
    with pytest.raises(ValueError, match="closure"):
        ReviewTask(
            id=task.id,
            tenant_id=TENANT,
            node_id=task.node_id,
            attribute_key="turnover_band",
            reason=task.reason,
            as_of_fy=FY,
            open=True,
            created_at=AT,
            closed_at=AT,
        )
    with pytest.raises(ValueError, match="answered"):
        ReviewTask(
            id=task.id,
            tenant_id=TENANT,
            node_id=task.node_id,
            attribute_key="turnover_band",
            reason=task.reason,
            as_of_fy=FY,
            open=False,
            created_at=AT,
            closed_at=AT,
            closed_by=ReviewClosedBy.ANSWER,
            outcome=ReviewOutcome.CONFIRMED,
        )


# ---------------------------------------------------------------- the use cases


def test_an_answer_closes_the_task_that_asked_for_it_and_only_that(ontology: Ontology) -> None:
    store = MemoryStore()
    node = entity(store, TENANT)
    opened = ConfirmFinancialYear(store, ontology, clock=clock).run(TENANT, FY)
    assert len(opened) == 1, "the turnover band of the year"
    (confirm_id,) = opened
    first = answer(
        store, ontology, node, AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE)
    )
    assert len(first.review_tasks) == 1, "a does-not-apply answer opens its task"
    assert first.closed_review_tasks == ()
    (not_applicable_id,) = first.review_tasks

    unsure = answer(
        store,
        ontology,
        node,
        AttributeChange("turnover_band", state=ValueState.UNSURE, as_of_fy=FY),
    )
    assert unsure.closed_review_tasks == (), "unsure answers nothing"

    other_year = answer(
        store, ontology, node, AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FY.next())
    )
    assert other_year.closed_review_tasks == (), "another year is another question"

    result = answer(
        store, ontology, node, AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FY)
    )
    assert result.closed_review_tasks == (confirm_id,)
    with store(TENANT) as uow:
        assert [task.id for task in uow.profiles.open_review_tasks(node)] == [not_applicable_id]
        closed = uow.profiles.get_review_task(confirm_id)
        every = uow.profiles.review_tasks(node)
    assert closed is not None
    assert (closed.open, closed.closed_by, closed.outcome, closed.closed_at) == (
        False,
        ReviewClosedBy.ANSWER,
        ReviewOutcome.ANSWERED,
        clock(),
    )
    assert {task.id for task in every} == {confirm_id, not_applicable_id}
    (entry,) = closed_entries(store)
    assert (entry.tenant_id, entry.subject_type, entry.subject_id) == (
        TENANT,
        "review_task",
        str(confirm_id),
    )
    assert entry.before == {"open": True}
    assert entry.after == {
        "open": False,
        "closed_by": "answer",
        "outcome": "answered",
        "reason": "confirm_financial_year",
        "attribute_key": "turnover_band",
        "node_id": str(node),
        "as_of_fy": "2000-01",
    }
    assert entry.reason == ""

    # The year's confirmation never reopens a task that was answered or closed.
    assert ConfirmFinancialYear(store, ontology, clock=clock).run(TENANT, FY) == ()
    # A known value stands in the snapshot, and a does-not-apply answer closes the task asking
    # about the value as well (it opens the review of the answer itself).
    again = answer(
        store,
        ontology,
        node,
        AttributeChange("employee_count", 12),
        AttributeChange("employee_count", 12),
    )
    assert again.closed_review_tasks == (not_applicable_id,)
    assert len(closed_entries(store)) == 2


def test_a_person_resolves_a_task_once_and_the_confirmation_leaves_it_closed(
    ontology: Ontology,
) -> None:
    store = MemoryStore()
    node = entity(store, TENANT)
    (task_id,) = ConfirmFinancialYear(store, ontology, clock=clock).run(TENANT, FY)
    resolve = ResolveReviewTask(store, clock=clock)
    resolved = resolve.run(
        TENANT, node, task_id, outcome=ReviewOutcome.DISMISSED, note="Example: not trading yet"
    )
    assert (resolved.open, resolved.closed_by, resolved.outcome, resolved.note) == (
        False,
        ReviewClosedBy.RESOLVE,
        ReviewOutcome.DISMISSED,
        "Example: not trading yet",
    )
    with pytest.raises(ReviewTaskClosedError):
        resolve.run(TENANT, node, task_id, outcome=ReviewOutcome.CONFIRMED)
    with pytest.raises(ReviewTaskNotFoundError):
        resolve.run(TENANT, node, BusinessId.new(), outcome=ReviewOutcome.CONFIRMED)
    other_node = entity(store, TENANT, Pan("ZZZZZ9999Z"))
    with pytest.raises(ReviewTaskNotFoundError):
        resolve.run(TENANT, other_node, task_id, outcome=ReviewOutcome.CONFIRMED)
    with pytest.raises(ProfileNodeNotFoundError):
        ResolveReviewTask(store, clock=clock).run(
            OTHER_TENANT, node, task_id, outcome=ReviewOutcome.CONFIRMED
        )
    (entry,) = closed_entries(store)
    assert (entry.after["closed_by"], entry.after["outcome"], entry.reason) == (
        "resolve",
        "dismissed",
        "Example: not trading yet",
    )
    confirm = ConfirmFinancialYear(store, ontology, clock=clock)
    reopened = confirm.run(TENANT, FY)
    with store(TENANT) as uow:
        nodes = {uow.profiles.get_review_task(task_id).node_id for task_id in reopened}  # type: ignore[union-attr]
    assert nodes == {other_node}, "a dismissed task stays dismissed; the new entity gets its own"
    assert confirm.run(TENANT, FY) == ()
    assert len(confirm.run(TENANT, FY.next())) == 2


def test_the_usage_and_tenant_directory_twins_count_across_tenants(ontology: Ontology) -> None:
    store = MemoryStore()
    first = entity(store, TENANT)
    second = entity(store, OTHER_TENANT)
    answer(store, ontology, first, AttributeChange("employee_count", 12))
    answer(
        store,
        ontology,
        first,
        AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FY),
        AttributeChange("turnover_band", "upto_10_lakh", as_of_fy=FY.next()),
    )
    answer(
        store,
        ontology,
        second,
        AttributeChange("employee_count", state=ValueState.NOT_APPLICABLE),
        tenant=OTHER_TENANT,
    )
    assert MemoryAttributeUsage(store).usage() == [
        AttributeUsage("employee_count", ValueState.KNOWN, 1),
        AttributeUsage("employee_count", ValueState.NOT_APPLICABLE, 1),
        AttributeUsage("turnover_band", ValueState.KNOWN, 1),
    ], "a per-year value counts its node once"
    assert MemoryTenantDirectory(store).tenants() == sorted(
        [TENANT, OTHER_TENANT], key=lambda tenant: tenant.value
    )
    assert MemoryTenantDirectory(MemoryStore()).tenants() == []


# ---------------------------------------------------------------- the routes


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(build_app(settings())) as test_client:
        yield test_client


def register(client: TestClient) -> str:
    response = client.post(
        "/v1/profile/entities", json={"pan": PAN.value, "name": "Example"}, headers=HEADERS
    )
    assert response.status_code == 201, response.text
    node: str = response.json()["id"]
    return node


def test_the_routes_show_a_task_closing_by_answer_and_by_resolve(client: TestClient) -> None:
    node = register(client)
    opened = client.post(
        "/v1/profile/financial-year-confirmations", json={"fy": "2000-01"}, headers=HEADERS
    )
    assert opened.status_code == 200, opened.text
    (confirm_id,) = opened.json()["opened"]
    not_applicable = client.put(
        f"/v1/profile/nodes/{node}/attributes",
        json={"changes": [{"key": "employee_count", "state": "not_applicable"}]},
        headers=HEADERS,
    ).json()
    (review_id,) = not_applicable["review_tasks"]
    assert not_applicable["closed_review_tasks"] == []

    answered = client.put(
        f"/v1/profile/nodes/{node}/attributes",
        json={
            "changes": [{"key": "turnover_band", "value": "upto_10_lakh", "as_of_fy": "2000-01"}]
        },
        headers=HEADERS,
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["closed_review_tasks"] == [confirm_id]
    open_tasks = client.get(f"/v1/profile/nodes/{node}/review-tasks", headers=HEADERS).json()
    assert [task["id"] for task in open_tasks] == [review_id]
    every = client.get(
        f"/v1/profile/nodes/{node}/review-tasks",
        params={"include_closed": "true"},
        headers=HEADERS,
    ).json()
    closed = next(task for task in every if task["id"] == confirm_id)
    assert (closed["open"], closed["closed_by"], closed["outcome"], closed["note"]) == (
        False,
        "answer",
        "answered",
        "",
    )
    assert closed["closed_at"] is not None
    snapshot = client.get(
        f"/v1/profile/nodes/{node}/snapshot", params={"fy": "2000-01"}, headers=HEADERS
    ).json()
    assert snapshot["attributes"]["turnover_band"] == "upto_10_lakh"

    path = f"/v1/profile/nodes/{node}/review-tasks/{review_id}/resolve"
    resolved = client.post(
        path, json={"outcome": "confirmed", "note": "Example: a one-person firm"}, headers=HEADERS
    )
    assert resolved.status_code == 200, resolved.text
    assert (resolved.json()["closed_by"], resolved.json()["outcome"], resolved.json()["note"]) == (
        "resolve",
        "confirmed",
        "Example: a one-person firm",
    )
    assert client.get(f"/v1/profile/nodes/{node}/review-tasks", headers=HEADERS).json() == []
    again = client.post(path, json={"outcome": "dismissed"}, headers=HEADERS)
    assert again.status_code == 409
    assert again.json()["type"].endswith(":profile-review-task-closed")
    unknown = client.post(
        f"/v1/profile/nodes/{node}/review-tasks/{uuid4()}/resolve",
        json={"outcome": "dismissed"},
        headers=HEADERS,
    )
    assert unknown.status_code == 404
    assert unknown.json()["type"].endswith(":profile-review-task-not-found")
    other_tenant = client.post(
        path, json={"outcome": "dismissed"}, headers={"x-tenant-id": str(uuid4())}
    )
    assert other_tenant.status_code == 404
    bad = client.post(path, json={"outcome": "answered"}, headers=HEADERS)
    assert bad.status_code == 422
    assert client.post(path, json={"outcome": "dismissed"}).status_code == 401


def test_in_token_mode_who_may_resolve_and_who_may_read_the_usage() -> None:
    issuer = TestIssuer()
    app: FastAPI = build_app(settings(**issuer.settings_overrides("token")))
    owner = bearer(issuer.user(TENANT, [Role.OWNER]))
    staff = bearer(issuer.user(TENANT, [Role.STAFF]))
    internal = TenantId.new()
    analyst = bearer(issuer.user(internal, [Role.ANALYST]))
    admin = bearer(issuer.user(internal, [Role.ADMIN]))
    usage = "/v1/profile/admin/attribute-usage"
    with TestClient(app) as client:
        node = client.post(
            "/v1/profile/entities", json={"pan": PAN.value, "name": "Example"}, headers=owner
        ).json()["id"]
        (task_id,) = client.post(
            "/v1/profile/financial-year-confirmations", json={"fy": "2000-01"}, headers=owner
        ).json()["opened"]
        path = f"/v1/profile/nodes/{node}/review-tasks/{task_id}/resolve"
        refused = client.post(path, json={"outcome": "dismissed"}, headers=staff)
        assert refused.status_code == 403, refused.text
        # The regulatory team has no grant on the resolve: a user acts in the tenant their token
        # names, so a grant could reach no customer's task; naming the tenant changes nothing.
        for regulatory in (analyst, admin):
            for headers in (regulatory, {**regulatory, **HEADERS}):
                refused = client.post(path, json={"outcome": "dismissed"}, headers=headers)
                assert refused.status_code == 403, refused.text
                assert refused.json()["type"].endswith(":auth-forbidden")
        resolved = client.post(path, json={"outcome": "dismissed"}, headers=owner)
        assert resolved.status_code == 200, resolved.text

        assert client.get(usage, headers=owner).status_code == 403
        assert client.get(usage, headers=staff).status_code == 403
        assert client.get(usage).status_code == 401
        counted = client.get(usage, headers=analyst)
        assert counted.status_code == 200, counted.text
        assert counted.json() == {"items": []}, "no value stored yet"
        client.put(
            f"/v1/profile/nodes/{node}/attributes",
            json={"changes": [{"key": "employee_count", "value": 3}]},
            headers=owner,
        )
        assert client.get(usage, headers=analyst).json()["items"] == [
            {"key": "employee_count", "state": "known", "count": 1}
        ]
        assert str(TENANT) not in client.get(usage, headers=analyst).text, "no tenant named"
