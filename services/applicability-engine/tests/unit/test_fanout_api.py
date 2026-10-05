"""The fan-out routes on the memory store: the runs newest first a page at a time, one run, the
controls with their audit entries and signals, the hold, the problems, and who may do what in
header, dual and token mode."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from applicability_engine.application.fanout_runs import BeginFanOut, RunUpdate, UpdateFanOut
from applicability_engine.domain.fanout import FanOutSignal, FanOutStart, FanOutStatus
from applicability_engine.infrastructure.memory import MemoryBusinessDirectory, MemoryStore
from applicability_engine.main import build_app
from applicability_engine.settings import ApplicabilityEngineSettings
from applicability_engine.testing import MemoryProfiles, MemoryRulebook
from applicability_engine.wiring import Readers
from domain_kernel.access import Role, Scope
from domain_kernel.audit import AuditActor
from domain_kernel.ids import EventId, RuleVersionId, TenantId, UserId
from domain_kernel.ontology import AttributeLevel
from py_common.auth.testing import TestIssuer, bearer
from py_common.settings import AuthMode

ENGINE = "/v1/applicability-engine"
FAN_OUTS = f"{ENGINE}/fan-outs"
HOLD = f"{ENGINE}/fan-out-hold"
REASON = "Checking the flips with the analysts"
ISSUER = TestIssuer()
INTERNAL = TenantId.new()
ADMIN_ID = UserId.new()
ADMIN = bearer(ISSUER.user(INTERNAL, [Role.ADMIN], mfa=True, user_id=ADMIN_ID))
REVIEWER = bearer(ISSUER.user(INTERNAL, [Role.REVIEWER], mfa=True))
ANALYST = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True))
OWNER = bearer(ISSUER.user(TenantId.new(), [Role.OWNER]))
SERVICE = bearer(ISSUER.service("applicability-engine", [Scope.TENANT_ACT]))
RUN_FIELDS = {
    "rule_version_id",
    "rule_key",
    "level",
    "status",
    "trigger_event_id",
    "supersedes",
    "businesses_total",
    "evaluated",
    "applies",
    "flips_compared",
    "flips",
    "flip_rate",
    "started_at",
    "updated_at",
    "finished_at",
    "status_reason",
    "status_by",
    "last_error",
}


class Signals:
    def __init__(self) -> None:
        self.sent: list[tuple[RuleVersionId, FanOutSignal]] = []

    def start(self, start: FanOutStart) -> bool:
        return False

    def signal(self, rule_version_id: RuleVersionId, signal: FanOutSignal) -> None:
        self.sent.append((rule_version_id, signal))


def app_in(mode: AuthMode) -> Iterator[tuple[TestClient, Signals]]:
    signals = Signals()
    settings = ApplicabilityEngineSettings(
        _env_file=None,
        service_name="applicability-engine",
        applicability_engine_store="memory",
        **ISSUER.settings_overrides(mode),
    )
    readers = Readers(profiles=MemoryProfiles(), rulebook=MemoryRulebook())
    with TestClient(build_app(settings, readers=readers, workflows=signals)) as client:
        yield client, signals


@pytest.fixture
def header_mode() -> Iterator[tuple[TestClient, Signals]]:
    yield from app_in("header")


@pytest.fixture
def dual_mode() -> Iterator[tuple[TestClient, Signals]]:
    yield from app_in("dual")


@pytest.fixture
def token_mode() -> Iterator[tuple[TestClient, Signals]]:
    yield from app_in("token")


def store_of(client: TestClient) -> MemoryStore:
    store = client.app.state.wiring.unit_of_work  # type: ignore[attr-defined]
    assert isinstance(store, MemoryStore)
    return store


def begin(client: TestClient, **changes: object) -> str:
    store = store_of(client)
    values: dict[str, object] = {
        "rule_version_id": RuleVersionId.new(),
        "rule_key": "gstr9_annual",
        "level": AttributeLevel.REGISTRATION,
        "trigger_event_id": EventId.new(),
    }
    values.update(changes)
    start = FanOutStart(**values)  # type: ignore[arg-type]
    BeginFanOut(store.fanouts, MemoryBusinessDirectory(store)).run(start)
    return str(start.rule_version_id)


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


def test_the_runs_are_listed_newest_first_a_page_at_a_time(
    header_mode: tuple[TestClient, Signals],
) -> None:
    client, _ = header_mode
    ids = [begin(client) for _ in range(3)]
    first = client.get(FAN_OUTS, params={"limit": 2})
    assert first.status_code == 200, first.text
    body = first.json()
    assert [run["rule_version_id"] for run in body["items"]] == ids[::-1][:2]
    assert set(body["items"][0]) == RUN_FIELDS
    assert body["items"][0]["status"] == "running"
    assert body["items"][0]["flip_rate"] is None
    rest = client.get(FAN_OUTS, params={"limit": 2, "cursor": body["next_cursor"]})
    assert [run["rule_version_id"] for run in rest.json()["items"]] == [ids[0]]
    assert rest.json()["next_cursor"] is None
    one = client.get(f"{FAN_OUTS}/{ids[0]}")
    assert (one.status_code, one.json()["rule_key"]) == (200, "gstr9_annual")
    missing = client.get(f"{FAN_OUTS}/{RuleVersionId.new()}")
    assert (missing.status_code, problem(missing)) == (404, "applicability-fan-out-not-found")


def test_the_controls_change_the_run_audit_it_and_signal_the_workflow(
    header_mode: tuple[TestClient, Signals],
) -> None:
    client, signals = header_mode
    rule_version_id = begin(client)
    paused = client.post(
        f"{FAN_OUTS}/{rule_version_id}/pause",
        json={"reason": REASON},
        headers={"x-request-id": "fan-out-request-1"},
    )
    assert paused.status_code == 200, paused.text
    assert (paused.json()["status"], paused.json()["status_reason"]) == ("paused", REASON)
    assert paused.json()["status_by"] == "system:applicability-engine", "no verified caller"
    again = client.post(f"{FAN_OUTS}/{rule_version_id}/pause", json={"reason": REASON})
    assert (again.status_code, problem(again)) == (409, "applicability-fan-out-state")
    resumed = client.post(f"{FAN_OUTS}/{rule_version_id}/resume")
    assert resumed.json()["status"] == "running"
    cancelled = client.post(f"{FAN_OUTS}/{rule_version_id}/cancel", json={"reason": REASON})
    assert (cancelled.json()["status"], cancelled.json()["finished_at"] is not None) == (
        "cancelled",
        True,
    )
    assert [signal for _, signal in signals.sent] == [
        FanOutSignal.PAUSE,
        FanOutSignal.RESUME,
        FanOutSignal.CANCEL,
    ]
    audit = store_of(client).audit
    assert [entry.action for entry in audit] == [
        "applicability.fanout.pause",
        "applicability.fanout.resume",
        "applicability.fanout.cancel",
    ]
    assert {entry.tenant_id for entry in audit} == {None}
    assert audit[0].correlation_id == "fan-out-request-1"
    assert audit[0].actor == AuditActor.system("applicability-engine")


def test_the_problems_of_the_controls(header_mode: tuple[TestClient, Signals]) -> None:
    client, _ = header_mode
    rule_version_id = begin(client)
    for path in ("pause", "cancel"):
        short = client.post(f"{FAN_OUTS}/{rule_version_id}/{path}", json={"reason": "  short  "})
        assert short.status_code == 422, "a reason of at least ten characters"
        none = client.post(f"{FAN_OUTS}/{rule_version_id}/{path}", json={})
        assert none.status_code == 422
    extra = client.post(f"{FAN_OUTS}/{rule_version_id}/resume", json={"reason": "", "x": 1})
    assert extra.status_code == 422
    missing = client.post(f"{FAN_OUTS}/{RuleVersionId.new()}/pause", json={"reason": REASON})
    assert (missing.status_code, problem(missing)) == (404, "applicability-fan-out-not-found")
    finished = begin(client)
    store = store_of(client)
    UpdateFanOut(store.fanouts).run(
        RunUpdate(RuleVersionId.parse(finished), status=FanOutStatus.COMPLETED)
    )
    late = client.post(f"{FAN_OUTS}/{finished}/cancel", json={"reason": REASON})
    assert (late.status_code, problem(late)) == (409, "applicability-fan-out-state")
    assert store.audit == []


def test_the_hold_is_set_read_and_released(header_mode: tuple[TestClient, Signals]) -> None:
    client, signals = header_mode
    assert client.get(HOLD).json() == {
        "held": False,
        "reason": None,
        "set_by": None,
        "set_at": None,
    }
    assert client.put(HOLD, json={"held": True}).status_code == 422
    assert client.put(HOLD, json={"held": True, "reason": "too short"}).status_code == 422
    held = client.put(HOLD, json={"held": True, "reason": "Deploy of the rulebook in progress"})
    assert held.status_code == 200, held.text
    assert (held.json()["held"], held.json()["set_by"]) == (True, "system:applicability-engine")
    assert client.get(HOLD).json()["reason"] == "Deploy of the rulebook in progress"
    rule_version_id = begin(client)
    UpdateFanOut(store_of(client).fanouts).run(
        RunUpdate(RuleVersionId.parse(rule_version_id), status=FanOutStatus.HELD)
    )
    released = client.put(HOLD, json={"held": False})
    assert released.json() == {"held": False, "reason": None, "set_by": None, "set_at": None}
    assert signals.sent == [(RuleVersionId.parse(rule_version_id), FanOutSignal.RESUME)]
    assert client.put(HOLD, json={"held": False, "reason": ""}).status_code == 200
    actions = [entry.action for entry in store_of(client).audit]
    assert actions == ["applicability.fanout.hold", "applicability.fanout.release"]


def test_in_token_mode_the_regulatory_team_reads_and_an_admin_controls(
    token_mode: tuple[TestClient, Signals],
) -> None:
    client, _ = token_mode
    rule_version_id = begin(client)
    for reader in (ADMIN, REVIEWER, ANALYST):
        assert client.get(FAN_OUTS, headers=reader).status_code == 200
        assert client.get(HOLD, headers=reader).status_code == 200
        assert client.get(f"{FAN_OUTS}/{rule_version_id}", headers=reader).status_code == 200
    for refused in (OWNER, SERVICE):
        answer = client.get(FAN_OUTS, headers=refused)
        assert (answer.status_code, problem(answer)) == (403, "auth-forbidden")
    anonymous = client.get(FAN_OUTS)
    assert (anonymous.status_code, problem(anonymous)) == (401, "auth-token-required")
    for refused in (REVIEWER, ANALYST, OWNER, SERVICE):
        answer = client.post(
            f"{FAN_OUTS}/{rule_version_id}/pause", json={"reason": REASON}, headers=refused
        )
        assert (answer.status_code, problem(answer)) == (403, "auth-forbidden")
        hold = client.put(HOLD, json={"held": True, "reason": REASON}, headers=refused)
        assert hold.status_code == 403
    paused = client.post(
        f"{FAN_OUTS}/{rule_version_id}/pause", json={"reason": REASON}, headers=ADMIN
    )
    assert (paused.status_code, paused.json()["status_by"]) == (200, str(ADMIN_ID))
    held = client.put(HOLD, json={"held": True, "reason": REASON}, headers=ADMIN)
    assert held.json()["set_by"] == str(ADMIN_ID)
    pause, hold_entry = store_of(client).audit
    assert pause.actor == AuditActor.user(ADMIN_ID, [Role.ADMIN])
    assert hold_entry.actor == pause.actor


def test_in_dual_mode_a_control_needs_a_token_but_a_read_does_not(
    dual_mode: tuple[TestClient, Signals],
) -> None:
    client, _ = dual_mode
    rule_version_id = begin(client)
    assert client.get(FAN_OUTS).status_code == 200
    answer = client.post(f"{FAN_OUTS}/{rule_version_id}/pause", json={"reason": REASON})
    assert (answer.status_code, problem(answer)) == (401, "auth-token-required")
    hold = client.put(HOLD, json={"held": True, "reason": REASON})
    assert (hold.status_code, problem(hold)) == (401, "auth-token-required")
    admin = client.post(
        f"{FAN_OUTS}/{rule_version_id}/pause", json={"reason": REASON}, headers=ADMIN
    )
    assert admin.status_code == 200
