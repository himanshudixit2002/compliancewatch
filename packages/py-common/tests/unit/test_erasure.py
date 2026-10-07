"""The erasure consumers' common part: it reads the deletion request, checks it with identity,
erases through the service's eraser and records the answer, refuses an event identity did not
send, only logs while the flag is off for the tenant, and keeps an erased tenant out of the
service's other consumers."""

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx2
import pytest
from sqlalchemy import Connection, create_engine, select
from sqlalchemy.pool import NullPool

from domain_kernel.audit import AuditEntry
from domain_kernel.erasure import (
    DELETION_REQUESTED_TOPIC,
    ERASURE_REFUSED_ACTION,
    Erased,
    ErasureCheck,
    TenantDataErased,
    retained,
)
from domain_kernel.ids import EventId, TenantId
from py_common import flags as flags_module
from py_common.erasure import (
    ErasurePlan,
    ErasureRefusedError,
    ErasureSwitch,
    HttpErasureVerifier,
    IdentityUnreachableError,
    MalformedDeletionRequestError,
    MemoryErasedTenants,
    apply_erasure,
    deletion_request_from,
    erased_on_connection,
    erasure_component,
    erasure_switch,
    plan_erasure,
    reset_flags_once,
    skip_erased,
    skip_erased_write,
)
from py_common.events import EventMessage, encode, payload_of
from py_common.flags import reset_flags
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    processed_event,
    read_first_store,
)
from py_common.outbox.testing import FakeProducer
from py_common.settings import Settings

AT = datetime(2000, 1, 12, 4, 30, tzinfo=UTC)
TENANT = TenantId.new()


def message(tenant: TenantId | None = TENANT, **payload: Any) -> EventMessage:
    body: dict[str, Any] = {
        "requested_by": None,
        "requested_at": "2000-01-11T10:00:00+05:30",
        "deadline_at": "2000-02-10T10:00:00+05:30",
        "retain_audit": True,
        "reason": "",
    }
    body.update(payload)
    return EventMessage(
        event_id=uuid4(),
        topic=DELETION_REQUESTED_TOPIC,
        schema_version="1.0.1",
        occurred_at=AT,
        tenant_id=None if tenant is None else tenant.value,
        correlation_id=uuid4(),
        causation_id=None,
        payload=body,
    )


@dataclass
class FakeEraser:
    erased: Erased = field(default_factory=lambda: Erased({"widget": 2}, retained(("log", "x"))))
    tenants: list[TenantId] = field(default_factory=list)
    recorded: list[tuple[TenantDataErased, AuditEntry]] = field(default_factory=list)
    audited: list[AuditEntry] = field(default_factory=list)

    def erase(self, tenant_id: TenantId) -> Erased:
        self.tenants.append(tenant_id)
        return self.erased

    def record(self, event: TenantDataErased, entry: AuditEntry) -> None:
        self.recorded.append((event, entry))

    def write_audit(self, entry: AuditEntry) -> None:
        self.audited.append(entry)


@dataclass
class FakeIdentity:
    """Identity's answer: by default, the tenant is being deleted and the event is the one sent."""

    status: str | None = "deletion_requested"
    internal: bool = False
    event_id: EventId | None = None
    """None: the event the test sends; set ``open_request=False`` for no open request."""
    open_request: bool = True
    down: bool = False
    asked: list[TenantId] = field(default_factory=list)
    sent: list[EventMessage] = field(default_factory=list)

    def check(self, tenant_id: TenantId) -> ErasureCheck:
        self.asked.append(tenant_id)
        if self.down:
            raise IdentityUnreachableError("identity unreachable: connection refused")
        current = self.event_id or (EventId(self.sent[-1].event_id) if self.sent else None)
        return ErasureCheck(
            tenant_id,
            self.status,
            internal=self.internal,
            deletion_event_id=current if self.open_request else None,
        )

    def sends(self, sent: EventMessage) -> EventMessage:
        self.sent.append(sent)
        return sent


def test_it_reads_the_request_the_message_carries() -> None:
    sent = message()
    request = deletion_request_from(sent)
    assert request.tenant_id == TENANT
    assert request.event_id.value == sent.event_id
    assert request.correlation_id.value == sent.correlation_id
    assert request.deadline_at - request.requested_at == timedelta(days=30)
    assert request.retain_audit


@pytest.mark.parametrize(
    "sent",
    [
        message(tenant=None),
        message(retain_audit="yes"),
        message(deadline_at="soon"),
        message(requested_at="2000-01-11T10:00:00"),
    ],
    ids=["no tenant", "retain_audit", "deadline", "naive"],
)
def test_a_malformed_request_raises(sent: EventMessage) -> None:
    with pytest.raises(MalformedDeletionRequestError):
        deletion_request_from(sent)


def test_with_the_flag_on_it_checks_with_identity_erases_and_records_the_answer() -> None:
    eraser, identity = FakeEraser(), FakeIdentity()
    sent = identity.sends(message())
    plan = plan_erasure("profile", sent, enabled=lambda _: True, verifier=identity)
    assert plan is not None
    assert plan.refusal is None
    assert identity.asked == [TENANT]
    event = apply_erasure("profile", plan, eraser, clock=lambda: AT)
    assert eraser.tenants == [TENANT]
    [(recorded, entry)] = eraser.recorded
    assert recorded == event
    assert (event.service, event.tenant_id, event.erased_at) == ("profile", TENANT, AT)
    assert event.causation_id is not None
    assert event.causation_id.value == sent.event_id
    assert payload_of(event)["tables"] == {"widget": 2}
    assert payload_of(event)["retained"] == [{"table": "log", "reason": "x"}]
    assert (entry.action, entry.tenant_id) == ("tenant.erased", TENANT)


def test_with_the_flag_off_it_only_logs_and_asks_identity_nothing() -> None:
    identity = FakeIdentity()
    asked: list[TenantId] = []

    def enabled(tenant: TenantId) -> bool:
        asked.append(tenant)
        return False

    assert plan_erasure("profile", message(), enabled=enabled, verifier=identity) is None
    assert asked == [TENANT]
    assert identity.asked == []


def test_another_topic_is_ignored() -> None:
    identity = FakeIdentity()
    other = message().model_copy(update={"topic": "tenant.created"})
    assert plan_erasure("profile", other, enabled=lambda _: True, verifier=identity) is None
    assert identity.asked == []


@pytest.mark.parametrize(
    ("identity", "reason"),
    [
        (FakeIdentity(event_id=EventId.new()), "not the one identity sent"),
        (FakeIdentity(open_request=False), "no open deletion request"),
        (FakeIdentity(status="active"), "the tenant is active"),
        (FakeIdentity(internal=True), "the internal tenant is never erased"),
        (FakeIdentity(status=None), "identity holds no such tenant"),
    ],
    ids=["another event", "no request", "active", "internal", "unknown"],
)
def test_an_event_identity_did_not_send_erases_nothing_and_is_audited(
    identity: FakeIdentity, reason: str
) -> None:
    eraser = FakeEraser()
    sent = identity.sends(message())
    plan = plan_erasure("profile", sent, enabled=lambda _: True, verifier=identity)
    assert plan is not None
    assert plan.refusal is not None
    assert reason in plan.refusal
    with pytest.raises(ErasureRefusedError, match=reason):
        apply_erasure("profile", plan, eraser, clock=lambda: AT)
    assert (eraser.tenants, eraser.recorded) == ([], [])
    [entry] = eraser.audited
    assert (entry.action, entry.tenant_id) == (ERASURE_REFUSED_ACTION, TENANT)
    assert entry.after is not None
    assert reason in str(entry.after["refused"])
    assert entry.after["deletion_event_id"] == str(sent.event_id)


def test_identity_unreachable_erases_nothing_and_raises_for_a_retry() -> None:
    identity = FakeIdentity(down=True)
    with pytest.raises(IdentityUnreachableError):
        plan_erasure("profile", message(), enabled=lambda _: True, verifier=identity)


def _consumer(tmp_path: Path, component: Any, name: str) -> IdempotentConsumer:
    engine = create_engine(f"sqlite:///{tmp_path / f'{name}.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    return IdempotentConsumer(
        group_id=component.group_id,
        store=read_first_store(engine, component.group_id),
        handler=component.handler,
        producer=FakeProducer(),
        config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
    )


def _record(sent: EventMessage) -> InboundRecord:
    return InboundRecord(
        topic=DELETION_REQUESTED_TOPIC, partition=0, offset=0, key=b"k", value=encode(sent)
    )


def test_the_component_is_the_service_s_erasure_group(tmp_path: Path) -> None:
    eraser, identity = FakeEraser(), FakeIdentity()
    component = erasure_component(
        "obligation", lambda _: eraser, enabled=lambda _: True, verifier=identity
    )
    assert component.group_id == "obligation.erasure"
    assert component.topics == (DELETION_REQUESTED_TOPIC,)
    assert component.dead_letter_topics() == ("tenant.deletion.requested.obligation.erasure.dlq",)
    assert component.store_factory is read_first_store, "no transaction open while identity answers"
    consumer = _consumer(tmp_path, component, "inbox")
    record = _record(identity.sends(message()))
    assert asyncio.run(consumer.process(record)) is Outcome.PROCESSED
    assert asyncio.run(consumer.process(record)) is Outcome.SKIPPED, "a redelivery erases once"
    assert len(eraser.tenants) == 1
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    with engine.connect() as connection:
        assert connection.execute(select(processed_event.c.consumer_group)).scalars().all() == [
            "obligation.erasure"
        ]


def test_the_component_dead_letters_a_refused_event_at_once(tmp_path: Path) -> None:
    eraser, identity = FakeEraser(), FakeIdentity(event_id=EventId.new())
    component = erasure_component(
        "obligation", lambda _: eraser, enabled=lambda _: True, verifier=identity
    )
    consumer = _consumer(tmp_path, component, "refused")
    assert asyncio.run(consumer.process(_record(message()))) is Outcome.REFUSED
    assert len(identity.asked) == 1, "a refusal is not retried"
    assert eraser.tenants == []
    assert [entry.action for entry in eraser.audited] == [ERASURE_REFUSED_ACTION]


def test_the_component_retries_while_identity_is_down_and_never_erases(tmp_path: Path) -> None:
    eraser, identity = FakeEraser(), FakeIdentity(down=True)
    component = erasure_component(
        "obligation", lambda _: eraser, enabled=lambda _: True, verifier=identity
    )
    consumer = _consumer(tmp_path, component, "down")
    assert asyncio.run(consumer.process(_record(message()))) is Outcome.DEAD
    assert len(identity.asked) == 2, "the inbox's retries, then the dead letters"
    assert (eraser.tenants, eraser.audited) == ([], [])


def _verifier(answer: httpx2.Response | Exception) -> tuple[HttpErasureVerifier, list[Any]]:
    seen: list[Any] = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        if isinstance(answer, Exception):
            raise answer
        return answer

    client = httpx2.Client(base_url="http://identity.test", transport=httpx2.MockTransport(respond))
    return HttpErasureVerifier("http://identity.test", client=client), seen


def test_the_http_verifier_reads_identity_s_check() -> None:
    event_id = EventId.new()
    body = {
        "tenant_id": str(TENANT),
        "status": "deletion_requested",
        "internal": False,
        "deletion_event_id": str(event_id),
    }
    verifier, seen = _verifier(httpx2.Response(200, json=body))
    assert verifier.check(TENANT) == ErasureCheck(
        TENANT, "deletion_requested", deletion_event_id=event_id
    )
    assert seen[0].url.path == f"/v1/identity/erasures/{TENANT}"
    internal, _ = _verifier(
        httpx2.Response(200, json={**body, "internal": True, "deletion_event_id": None})
    )
    assert internal.check(TENANT) == ErasureCheck(TENANT, "deletion_requested", internal=True)
    unknown, _ = _verifier(
        httpx2.Response(
            404, json={"type": "https://compliancewatch.in/problems/identity-tenant-not-found"}
        )
    )
    assert unknown.check(TENANT) == ErasureCheck(TENANT, None)


@pytest.mark.parametrize(
    "answer",
    [
        httpx2.Response(404, json={"type": "https://compliancewatch.in/problems/route-not-found"}),
        httpx2.Response(403, json={"type": "https://compliancewatch.in/problems/auth-forbidden"}),
        httpx2.Response(503, text="down"),
        httpx2.Response(200, json={"status": "erased"}),
        httpx2.Response(200, text="not json"),
        httpx2.ConnectError("connection refused"),
    ],
    ids=["route missing", "forbidden", "unavailable", "unreadable", "not json", "unreachable"],
)
def test_the_http_verifier_raises_for_a_retry_on_anything_else(
    answer: httpx2.Response | Exception,
) -> None:
    verifier, _ = _verifier(answer)
    with pytest.raises(IdentityUnreachableError):
        verifier.check(TENANT)


def test_the_erased_markers_keep_the_first_erasure() -> None:
    markers = MemoryErasedTenants()
    event = TenantDataErased(
        tenant_id=TENANT,
        service="profile",
        deletion_event_id=EventId.new(),
        erased_at=AT,
    )
    assert markers.mark(event)
    assert not markers.mark(event)
    assert markers.is_erased(TENANT)
    assert not markers.is_erased(TenantId.new())
    assert [marker.erased_at for marker in markers] == [AT]
    assert len(markers) == 1


def test_an_erased_tenant_s_event_is_marked_processed_and_writes_nothing() -> None:
    markers = MemoryErasedTenants()
    markers.mark(
        TenantDataErased(
            tenant_id=TENANT, service="profile", deletion_event_id=EventId.new(), erased_at=AT
        )
    )
    written: list[str] = []

    def handler(sent: EventMessage, _: Connection) -> None:
        written.append(str(sent.tenant_id))

    def write(sent: EventMessage, plan: str, _: Connection) -> None:
        written.append(plan)

    guarded = skip_erased("profile", handler, erased_on=lambda _: markers)
    guarded_write = skip_erased_write("profile", write, erased_on=lambda _: markers)
    connection: Any = None
    guarded(message(), connection)
    guarded_write(message(), "plan", connection)
    assert written == [], "the erased tenant's events write nothing"
    other = TenantId.new()
    guarded(message(other), connection)
    guarded_write(message(other), "plan", connection)
    guarded(message(None), connection)
    assert written == [str(other.value), "plan", "None"]


@pytest.fixture
def flags() -> Iterator[None]:
    reset_flags_once()
    yield
    reset_flags()
    reset_flags_once()


@pytest.mark.usefixtures("flags")
def test_the_switch_reads_the_flag_per_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    other = TenantId.new()
    monkeypatch.setenv("CW_TENANT_ERASURE_ENABLED", "true")
    monkeypatch.setenv("CW_TENANT_ERASURE_TENANTS", str(TENANT))
    switch = ErasureSwitch(Settings(_env_file=None, service_name="profile-worker"))
    assert switch(TENANT)
    assert not switch(other)


@pytest.mark.usefixtures("flags")
def test_the_switch_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CW_TENANT_ERASURE_ENABLED", raising=False)
    monkeypatch.delenv("CW_FLAG_IDENTITY_TENANT_ERASURE", raising=False)
    switch = ErasureSwitch(Settings(_env_file=None, service_name="profile-worker"))
    assert not switch(TENANT)


@pytest.mark.usefixtures("flags")
def test_the_process_configures_its_flags_once_for_every_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured: list[Settings] = []
    real = flags_module.configure_flags

    def counting(settings: Settings) -> Any:
        configured.append(settings)
        return real(settings)

    monkeypatch.setattr("py_common.erasure.configure_flags", counting)
    monkeypatch.setenv("CW_TENANT_ERASURE_ENABLED", "true")
    monkeypatch.delenv("CW_TENANT_ERASURE_TENANTS", raising=False)
    switches = [
        erasure_switch(Settings(_env_file=None, service_name=f"{service}-worker"))
        for service in ("identity", "profile", "obligation", "notification", "rulebook")
    ]
    assert all(switch is switches[0] for switch in switches), "one reader for the worker"
    assert all(switch(TenantId.new()) for switch in switches)
    assert ErasureSwitch(Settings(_env_file=None, service_name="x"))(TENANT)
    assert len(configured) == 1


def test_a_plan_without_refusal_is_an_erasure() -> None:
    request = deletion_request_from(message())
    assert ErasurePlan(request).refusal is None
    assert ErasurePlan(request, "why").refusal == "why"


def test_the_default_check_reads_no_markers_off_postgres(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'other.sqlite'}", poolclass=NullPool)
    with engine.connect() as connection:
        assert not erased_on_connection(connection).is_erased(TENANT)
