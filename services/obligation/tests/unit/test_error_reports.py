"""Error reports on the memory store, over HTTP in header mode and through the worker's consumer
of error_report.decided: the route behind its flag (404 and nothing stored while it is off), a
report of another tenant's obligation (404), the report kept as written while the event leaves
masked and the audit row names no text, the Idempotency-Key, the tenant's list with its status
filter and pages, the decision applied once (confirmed with the correcting version, rejected, a
redelivery or a replay changing nothing, a report the tenant has no row of dead-lettered, an
erased tenant's decision only marked processed), the export section and the domain's own
rules."""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import NullPool

from domain_kernel.erasure import TenantDataErased
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EventId, ObligationId, RuleVersionId, TenantId, UserId
from obligation import worker
from obligation.application.error_reports import (
    DECIDED_ACTION,
    SUBMITTED_ACTION,
    ApplyErrorDecision,
    report_description,
)
from obligation.application.export import ExportTenantData
from obligation.application.materialise import MaterialiseRequest
from obligation.domain.error_reports import (
    ErrorCategory,
    ErrorOutcome,
    ErrorReport,
    ErrorReportId,
    ErrorReportStatus,
    ErrorReportSubmitted,
)
from obligation.domain.errors import ErrorReportDecidedError
from obligation.domain.flags import ERROR_REPORTS
from obligation.infrastructure.flags import StaticFlags
from obligation.infrastructure.memory import MemoryStore
from obligation.main import build_app
from obligation.settings import ObligationSettings
from obligation.testing import BUSINESS, DECISION, OTHER_TENANT, TENANT, FakeRuleVersionReader, rule
from py_common.idempotency.fastapi import REPLAYED_HEADER
from py_common.outbox import (
    ConsumerConfig,
    IdempotentConsumer,
    InboundRecord,
    Outcome,
    SyncProcessedStore,
    processed_event,
)
from py_common.outbox.testing import FakeProducer

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
DECIDED = EXAMPLES / "error_report.decided"
ROUTE = "/v1/obligation/obligations"
LIST = "/v1/obligation/error-reports"
DLQ = "error_report.decided.obligation.error-decisions.dlq"
NOW = datetime(2026, 10, 1, 4, 0, tzinfo=UTC)
TEXT = (
    "Example: the example monthly statement shows the 20th as its due date, but the example "
    "notice gives the 25th. Call us on +91 98765 43210 or write to owner@example.org."
)


class Api:
    """The app on the memory store with the flag on (or off), one monthly rule materialised
    for the tenant, and requests in header mode."""

    def __init__(self, *, on: bool = True) -> None:
        self.rule = rule()
        self.reader = FakeRuleVersionReader([self.rule])
        settings = ObligationSettings(
            _env_file=None, service_name="obligation", obligation_store="memory"
        )
        self.app: FastAPI = build_app(
            settings, rules=self.reader, flags=StaticFlags(ERROR_REPORTS) if on else StaticFlags()
        )
        made = self.app.state.wiring.materialise.run(
            MaterialiseRequest(
                TENANT, BUSINESS, DECISION, self.rule, date(2026, 9, 28), profile_version=3
            )
        )
        self.first: ObligationId = made.created[0]
        self.store.audit.clear()
        self.store.events.clear()
        self.client = TestClient(self.app)

    @property
    def store(self) -> MemoryStore:
        store = self.app.state.wiring.unit_of_work
        assert isinstance(store, MemoryStore)
        return store

    def report(
        self,
        description: str = TEXT,
        *,
        category: str = "due_date",
        obligation_id: object = None,
        tenant: object = TENANT,
        key: str | None = None,
    ) -> Any:
        headers = {"x-tenant-id": str(tenant), "Idempotency-Key": key or uuid4().hex}
        return self.client.post(
            f"{ROUTE}/{obligation_id or self.first}/error-reports",
            json={"category": category, "description": description},
            headers=headers,
        )

    def listed(self, tenant: object = TENANT, **params: Any) -> Any:
        return self.client.get(LIST, params=params, headers={"x-tenant-id": str(tenant)})

    def submitted(self) -> list[ErrorReportSubmitted]:
        return [e for e in self.store.events if isinstance(e, ErrorReportSubmitted)]


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


# ---------------------------------------------------------------- the report route


def test_with_the_flag_off_the_route_is_404_and_nothing_is_stored() -> None:
    api = Api(on=False)
    answered = api.report()
    assert (answered.status_code, problem(answered)) == (404, "obligation-error-reports-disabled")
    assert api.store.error_reports == {}
    assert api.submitted() == []
    assert api.store.audit == []
    assert api.listed().status_code == 200, "the list route answers either way"
    assert api.listed().json() == {"items": [], "next_cursor": None}


def test_a_report_is_kept_as_written_and_leaves_masked() -> None:
    api = Api()
    answered = api.report(key="report-1")
    assert answered.status_code == 201, answered.text
    body = answered.json()
    assert (body["obligation_id"], body["business_id"], body["rule_version_id"]) == (
        str(api.first),
        str(BUSINESS),
        str(api.rule.rule_version_id),
    )
    assert (body["category"], body["status"], body["description"]) == (
        "due_date",
        "submitted",
        TEXT,
    )
    assert (body["submitted_by"], body["decided_at"], body["notes"]) == (None, None, "")
    assert body["correcting_rule_version_id"] is None
    report_id = ErrorReportId(UUID(body["report_id"]))
    stored = api.store.error_reports[report_id]
    assert stored.description == TEXT, "the tenant's own row keeps the reporter's text"
    assert stored.tenant_id == TENANT
    assert stored.is_open

    (event,) = api.submitted()
    assert (event.tenant_id, event.report_id, event.obligation_id) == (TENANT, report_id, api.first)
    assert "[PHONE]" in event.description
    assert "[EMAIL]" in event.description
    assert "98765" not in event.description
    assert "example.org" not in event.description
    assert event.category is ErrorCategory.DUE_DATE
    assert event.submitted_at == stored.submitted_at

    (entry,) = api.store.audit
    assert (entry.action, entry.subject_type, entry.subject_id, entry.tenant_id) == (
        SUBMITTED_ACTION,
        "error_report",
        str(report_id),
        TENANT,
    )
    assert entry.before is None
    assert entry.after == {
        "status": "submitted",
        "obligation_id": str(api.first),
        "business_id": str(BUSINESS),
        "rule_version_id": str(api.rule.rule_version_id),
        "category": "due_date",
    }
    assert "98765" not in str(entry.after), "the audit row names no text"

    replayed = api.report(key="report-1")
    assert replayed.status_code == 201
    assert replayed.headers[REPLAYED_HEADER] == "true"
    assert replayed.json()["report_id"] == body["report_id"]
    assert len(api.store.error_reports) == 1
    without_key = api.client.post(
        f"{ROUTE}/{api.first}/error-reports",
        json={"category": "other", "description": "Example"},
        headers={"x-tenant-id": str(TENANT)},
    )
    assert without_key.status_code == 428


def test_a_report_needs_the_tenants_obligation_and_a_description() -> None:
    api = Api()
    theirs = api.report(tenant=OTHER_TENANT)
    assert (theirs.status_code, problem(theirs)) == (404, "obligation-not-found")
    unknown = api.report(obligation_id=uuid4())
    assert (unknown.status_code, problem(unknown)) == (404, "obligation-not-found")
    for description in ("", "   ", "x" * 2001):
        refused = api.report(description)
        assert refused.status_code == 422, refused.text
    assert api.report(category="typo").status_code == 422
    assert api.store.error_reports == {}
    assert api.submitted() == []


def test_the_list_runs_newest_first_by_status_in_pages() -> None:
    api = Api()
    made = [
        api.report(f"Example report {n}", category=c).json()
        for n, c in enumerate(("due_date", "steps", "other"))
    ]
    reports = api.store.error_reports
    expected = sorted(reports.values(), key=lambda r: (r.submitted_at, r.id.value), reverse=True)
    assert len(made) == 3

    first = api.listed(limit=2)
    assert first.status_code == 200, first.text
    page = first.json()
    assert [i["report_id"] for i in page["items"]] == [str(r.id) for r in expected[:2]]
    assert page["next_cursor"]
    rest = api.listed(limit=2, cursor=page["next_cursor"]).json()
    assert [i["report_id"] for i in rest["items"]] == [str(expected[2].id)]
    assert rest["next_cursor"] is None
    assert api.listed(status="submitted").json()["items"] == api.listed().json()["items"]
    assert api.listed(status="confirmed").json()["items"] == []
    assert api.listed(status="typo").status_code == 422
    assert api.listed(tenant=OTHER_TENANT).json()["items"] == [], "another tenant sees nothing"
    assert api.listed(cursor="not-a-cursor").status_code == 422


# ---------------------------------------------------------------- the decision consumer


@pytest.fixture
def inbox(tmp_path: Path) -> Iterator[Engine]:
    engine = create_engine(f"sqlite:///{tmp_path / 'inbox.sqlite'}", poolclass=NullPool)
    processed_event.create(engine)
    yield engine
    engine.dispose()


class Decisions:
    """The worker's consumer of error_report.decided on a SQLite inbox and the api's store."""

    def __init__(self, inbox: Engine, api: Api) -> None:
        self.api = api
        self.producer = FakeProducer()
        self.consumer = IdempotentConsumer(
            group_id=worker.ERROR_DECISIONS_GROUP_ID,
            store=SyncProcessedStore(inbox, group_id=worker.ERROR_DECISIONS_GROUP_ID),
            handler=worker.error_decision_handler(
                ApplyErrorDecision(),
                units_on=lambda connection: api.store,
                erased_on=lambda connection: api.store.erased,
            ),
            producer=self.producer,
            config=ConsumerConfig(max_handler_attempts=2, retry_backoff_seconds=0),
        )

    def record(
        self,
        example: str,
        report: ErrorReport,
        *,
        offset: int = 0,
        event_id: UUID | None = None,
        tenant: TenantId = TENANT,
        topic: str = worker.ERROR_DECIDED_TOPIC,
        **payload: Any,
    ) -> InboundRecord:
        data = json.loads((DECIDED / f"{example}.json").read_text(encoding="utf-8"))
        data["topic"] = topic
        data["event_id"] = str(event_id or uuid4())
        data["tenant_id"] = str(tenant)
        data["payload"].update(
            {"report_id": str(report.id), "rule_version_id": str(report.rule_version_id)}
        )
        data["payload"].update(payload)
        return InboundRecord(
            topic=topic, partition=0, offset=offset, key=b"k", value=json.dumps(data).encode()
        )


def reported(api: Api) -> ErrorReport:
    answered = api.report()
    assert answered.status_code == 201, answered.text
    report = api.store.error_reports[ErrorReportId(UUID(answered.json()["report_id"]))]
    api.store.audit.clear()
    return report


async def test_a_confirmation_moves_the_report_once(inbox: Engine) -> None:
    api = Api()
    report = reported(api)
    decisions = Decisions(inbox, api)
    event_id = uuid4()
    confirmed = decisions.record("confirmed-with-correction", report, event_id=event_id)

    assert await decisions.consumer.process(confirmed) is Outcome.PROCESSED

    decided = api.store.error_reports[report.id]
    assert (decided.status, decided.correcting_rule_version_id) == (
        ErrorReportStatus.CONFIRMED,
        RuleVersionId(UUID("4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b")),
    )
    assert decided.decided_at == datetime(2000, 2, 4, 9, 40, tzinfo=UTC)
    assert decided.notes.startswith("Example: the notice of 2000-01")
    assert decided.description == TEXT, "the text is untouched"
    (entry,) = api.store.audit
    assert (entry.action, entry.subject_id, entry.actor.label) == (
        DECIDED_ACTION,
        str(report.id),
        "system:obligation",
    )
    assert (entry.before, entry.after) == (
        {"status": "submitted"},
        {
            "status": "confirmed",
            "rule_version_id": str(report.rule_version_id),
            "correcting_rule_version_id": "4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b",
        },
    )
    assert entry.correlation_id == str(event_id), "no request: the event's id"
    listed = api.listed(status="confirmed").json()["items"]
    assert [i["report_id"] for i in listed] == [str(report.id)]
    assert listed[0]["correcting_rule_version_id"] == "4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b"

    assert await decisions.consumer.process(confirmed) is Outcome.SKIPPED, "a redelivery"
    replay = decisions.record("rejected", report, offset=1)
    assert await decisions.consumer.process(replay) is Outcome.PROCESSED, "decided already"
    assert api.store.error_reports[report.id] == decided
    assert len(api.store.audit) == 1, "a decision is recorded once"
    ignored = decisions.record("rejected", report, offset=2, topic="rule.published")
    assert await decisions.consumer.process(ignored) is Outcome.PROCESSED
    assert decisions.producer.sent == []


async def test_a_rejection_keeps_the_notes_and_names_no_version(inbox: Engine) -> None:
    api = Api()
    report = reported(api)
    decisions = Decisions(inbox, api)
    assert await decisions.consumer.process(decisions.record("rejected", report)) is (
        Outcome.PROCESSED
    )
    decided = api.store.error_reports[report.id]
    assert (decided.status, decided.correcting_rule_version_id) == (
        ErrorReportStatus.REJECTED,
        None,
    )
    assert decided.notes.startswith("Example: the 20th is the date")


async def test_a_decision_the_tenant_has_no_report_of_is_dead_lettered(inbox: Engine) -> None:
    api = Api()
    report = reported(api)
    decisions = Decisions(inbox, api)
    theirs = decisions.record("rejected", report, tenant=OTHER_TENANT)
    assert await decisions.consumer.process(theirs) is Outcome.DEAD
    assert decisions.producer.topics() == [DLQ]
    assert api.store.error_reports[report.id].is_open
    refused = decisions.record("rejected", report, offset=1, outcome="typo")
    assert await decisions.consumer.process(refused) is Outcome.DEAD
    assert decisions.producer.topics() == [DLQ, DLQ]
    assert api.store.audit == []


async def test_a_decision_of_an_erased_tenant_is_only_marked_processed(inbox: Engine) -> None:
    api = Api()
    report = reported(api)
    api.store.erased.mark(
        TenantDataErased(
            tenant_id=TENANT, service="obligation", deletion_event_id=EventId.new(), erased_at=NOW
        )
    )
    decisions = Decisions(inbox, api)
    late = decisions.record("rejected", report)
    assert await decisions.consumer.process(late) is Outcome.PROCESSED
    assert await decisions.consumer.process(late) is Outcome.SKIPPED
    assert api.store.error_reports[report.id].is_open
    assert api.store.audit == []
    assert api.listed().status_code == 410, "the routes answer the erased tenant 410"


# ---------------------------------------------------------------- the export


def test_the_export_lists_the_reports_oldest_first() -> None:
    api = Api()
    first = api.report("Example first").json()
    second = api.report("Example second").json()
    found = ExportTenantData(api.store, lambda: NOW).run(TENANT)
    rows = found.sections["error_reports"]
    assert [row["id"] for row in rows] == [first["report_id"], second["report_id"]]
    assert rows[0]["description"] == "Example first"
    assert (rows[0]["status"], rows[0]["category"]) == ("submitted", "due_date")
    assert "tenant_id" not in rows[0], "the tenant is the export's"
    theirs = ExportTenantData(api.store, lambda: NOW).run(OTHER_TENANT)
    assert theirs.sections["error_reports"] == []


# ---------------------------------------------------------------- the domain's own rules


def report_of(**overrides: Any) -> ErrorReport:
    values: dict[str, Any] = {
        "id": ErrorReportId.new(),
        "tenant_id": TENANT,
        "obligation_id": ObligationId.new(),
        "business_id": BUSINESS,
        "rule_version_id": RuleVersionId.new(),
        "category": ErrorCategory.OTHER,
        "description": "Example: something else is wrong.",
        "status": ErrorReportStatus.SUBMITTED,
        "submitted_by": None,
        "submitted_at": NOW,
    }
    values.update(overrides)
    return ErrorReport(**values)


def test_a_report_is_decided_exactly_once_and_only_a_confirmation_names_a_version() -> None:
    report = report_of(submitted_by=UserId(UUID(int=5)))
    with pytest.raises(InvariantViolationError):
        report_of(status=ErrorReportStatus.CONFIRMED, decided_at=NOW)
    with pytest.raises(InvariantViolationError):
        report_of(status=ErrorReportStatus.REJECTED)
    with pytest.raises(InvariantViolationError):
        report_of(correcting_rule_version_id=RuleVersionId.new())
    with pytest.raises(InvariantViolationError):
        report_of(description="")
    with pytest.raises(InvariantViolationError):
        report_of(notes="x" * 2001)
    rejected = report.decide(ErrorOutcome.REJECTED, at=NOW + timedelta(days=1), notes="n")
    assert (rejected.status, rejected.notes, rejected.is_open) == (
        ErrorReportStatus.REJECTED,
        "n",
        False,
    )
    with pytest.raises(ErrorReportDecidedError):
        rejected.decide(
            ErrorOutcome.CONFIRMED, at=NOW, correcting_rule_version_id=RuleVersionId.new()
        )
    with pytest.raises(InvariantViolationError):
        # A confirmation names the version that corrects the reported one.
        report.decide(ErrorOutcome.CONFIRMED, at=NOW)
    assert report_description("  Example  ") == "Example"
    for text in ("", "   ", "x" * 2001):
        with pytest.raises(InvariantViolationError):
            report_description(text)
