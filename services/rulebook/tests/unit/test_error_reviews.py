"""Tenants' error reports on the memory store and over HTTP: the intake of error_report.submitted
(one review per report, a redelivery changes nothing, a payload the contract refuses or a version
the rulebook does not hold raises), the queue by rule version, oldest first, with its groups and
pages, the decisions (confirmed only with a version that has a corrects relation to the reported
one, rejected with notes, once), the error_report.decided outbox row keyed by the reporting
tenant, the audit entry, an erased tenant's review decided for the record without an event, and
the routes' problem types and actors in header and token mode."""

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from domain_kernel.access import Role
from domain_kernel.documents import Clause, DocumentType, clause_id_for, document_id_for
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ClauseId, ObligationId, RuleVersionId, SourceId, TenantId, UserId
from domain_kernel.knowledge import RelationKind, RuleRelation
from domain_kernel.status import RuleVersionStatus
from py_common.auth.testing import TestIssuer, bearer
from py_common.events import payload_of
from py_common.settings import AuthMode
from rulebook.application.documents import RegisterDocument
from rulebook.application.error_reports import (
    DECIDED_ACTION,
    DecideErrorReview,
    IntakeErrorReport,
    ListErrorReviews,
)
from rulebook.domain.documents import StoredDocument
from rulebook.domain.error_reports import (
    ErrorCategory,
    ErrorOutcome,
    ErrorReportDecided,
    ErrorReview,
    ErrorReviewKey,
    ErrorReviewQuery,
    ErrorReviewStatus,
    queue_position,
    review_id_for,
)
from rulebook.domain.errors import (
    CorrectingVersionRequiredError,
    ErrorReviewClosedError,
    ErrorReviewNotFoundError,
    UnknownRuleVersionError,
)
from rulebook.infrastructure.memory import MemoryKnowledgeStore
from rulebook.main import build_app
from rulebook.testing import REVIEW_TOKEN, rulebook_settings

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
EXAMPLE = EXAMPLES / "error_report.submitted" / "wrong-due-date.json"
START = datetime(2000, 2, 3, 5, 15, tzinfo=UTC)
TENANT = TenantId(UUID("5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a"))
OTHER_TENANT = TenantId(UUID("9d8c7b6a-5f4e-4d3c-8b2a-1a0f9e8d7c6b"))
ANALYST = UserId(UUID(int=71))
REVIEWER = UserId(UUID(int=72))
DIGEST = hashlib.sha256(b"example notice for the error reviews").hexdigest()
DOC = document_id_for(DIGEST)
CLAUSE: ClauseId = clause_id_for(DOC, "en.p1")
MONTHLY = "gstr3b_monthly"
QUARTERLY = "gstr1_quarterly"
BASE = "/v1/rulebook/error-reports"
REVIEW = {"x-cw-review-token": REVIEW_TOKEN}
ISSUER = TestIssuer()
INTERNAL = TenantId.new()
ANALYST_BEARER = bearer(ISSUER.user(INTERNAL, [Role.ANALYST], mfa=True, user_id=ANALYST))
OWNER_BEARER = bearer(ISSUER.user(TenantId.new(), [Role.OWNER]))


class Clock:
    """Moves one minute on every reading, so every report arrives at its own time."""

    def __init__(self, start: datetime = START) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> MemoryKnowledgeStore:
    return MemoryKnowledgeStore(clock)


def versions(store: MemoryKnowledgeStore) -> tuple[RuleVersionId, RuleVersionId, RuleVersionId]:
    """A published monthly version, the draft that corrects it, and another rule's version."""
    _, old = store.add_rule(
        MONTHLY,
        title="Monthly return (synthetic)",
        status=RuleVersionStatus.PUBLISHED,
        effective_from=date(2000, 1, 1),
    )
    new = store.add_version(
        MONTHLY, title="Monthly return, corrected (synthetic)", effective_from=date(2000, 3, 1)
    )
    _, other = store.add_rule(
        QUARTERLY, title="Quarterly statement (synthetic)", status=RuleVersionStatus.PUBLISHED
    )
    return old, new, other


def payload(version: RuleVersionId, **overrides: Any) -> dict[str, Any]:
    """The contract's example report, about ``version``, with a report id of its own."""
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))["payload"]
    data["rule_version_id"] = str(version)
    data["report_id"] = str(uuid4())
    data.update(overrides)
    return dict(data)


def relate(store: MemoryKnowledgeStore, x: RuleVersionId, y: RuleVersionId) -> None:
    """``x`` corrects ``y``, with a clause of a synthetic notice as the evidence."""
    with store() as uow:
        registered = uow.documents.get(DOC) is not None
    if not registered:
        RegisterDocument(store).run(
            StoredDocument(
                document_id=DOC,
                source_id=SourceId(UUID(int=7)),
                sha256=DIGEST,
                regulator="CBIC",
                doc_type=DocumentType.NOTIFICATION,
                url="https://example.invalid/notice.pdf",
                language="en",
                media_type="application/pdf",
                parser_version="pdf@1",
                fetched_at=START,
                published_at=date(2000, 1, 15),
            ),
            [Clause("en.p1", "Example notice: the example statement is due on the 25th.")],
        )
    with store() as uow:
        uow.relations.add(
            RuleRelation(x, RelationKind.CORRECTS, y, CLAUSE),
            relation_id=uuid4(),
            candidate_id=None,
        )


def problem(response: Any) -> str:
    kind: str = response.json()["type"]
    return kind.rsplit(":", 1)[-1]


# ---------------------------------------------------------------- the intake


def test_the_intake_keeps_one_review_per_report(store: MemoryKnowledgeStore, clock: Clock) -> None:
    old, _, _ = versions(store)
    intake = IntakeErrorReport(store, clock)
    report = payload(old)

    first = intake.run(TENANT, report)

    assert first.created
    review = first.review
    assert review.review_id == review_id_for(UUID(report["report_id"]))
    assert (review.report_id, review.tenant_id, review.rule_version_id) == (
        UUID(report["report_id"]),
        TENANT,
        old,
    )
    assert review.obligation_id == ObligationId(UUID(report["obligation_id"]))
    assert (review.category, review.description_masked) == (
        ErrorCategory.DUE_DATE,
        report["description"],
    ), "the text is kept as it arrived: the obligation service masked it"
    assert "[PHONE]" in review.description_masked
    assert (review.status, review.received_at) == (
        ErrorReviewStatus.OPEN,
        START + timedelta(minutes=1),
    )
    assert review.is_open

    again = intake.run(TENANT, {**report, "description": "Example: a redelivery with new text."})
    assert not again.created
    assert again.review == review, "the first delivery wins"
    assert [r.report_id for r in store.error_reviews()] == [review.report_id]


def test_the_intake_refuses_what_the_contract_or_the_rulebook_does_not_know(
    store: MemoryKnowledgeStore, clock: Clock
) -> None:
    old, _, _ = versions(store)
    intake = IntakeErrorReport(store, clock)
    with pytest.raises(ValidationError):
        intake.run(TENANT, payload(old, category="typo"))
    with pytest.raises(ValidationError):
        intake.run(TENANT, payload(old, description=""))
    with pytest.raises(UnknownRuleVersionError):
        intake.run(TENANT, payload(RuleVersionId.new()))
    assert store.error_reviews() == []


# ---------------------------------------------------------------- the queue


def test_the_queue_runs_by_rule_version_then_oldest_first_with_groups_and_pages(
    store: MemoryKnowledgeStore, clock: Clock
) -> None:
    old, _, other = versions(store)
    intake = IntakeErrorReport(store, clock)
    reviews = [
        intake.run(TENANT, payload(other)).review,
        intake.run(OTHER_TENANT, payload(old, category="steps")).review,
        intake.run(TENANT, payload(old)).review,
    ]
    expected = sorted(reviews, key=queue_position)
    listing = ListErrorReviews(store)

    assert listing.run() == expected
    first = listing.run(limit=2)
    assert first == expected[:2]
    rest = listing.run(after=ErrorReviewKey.of(first[-1]), limit=2)
    assert rest == expected[2:]
    assert listing.run(rule_version_id=old) == [r for r in expected if r.rule_version_id == old]
    assert listing.run(status=ErrorReviewStatus.REJECTED) == []
    assert listing.run(status=None) == expected

    groups = listing.groups()
    assert sorted(g.rule_version_id.value for g in groups) == sorted({old.value, other.value})
    by_version = {g.rule_version_id: g for g in groups}
    assert (by_version[old].open_count, by_version[old].rule_key, by_version[old].version) == (
        2,
        MONTHLY,
        1,
    )
    assert by_version[old].title == "Monthly return (synthetic)"
    assert by_version[old].oldest_received_at == min(
        r.received_at for r in reviews if r.rule_version_id == old
    )
    assert by_version[other].open_count == 1
    assert [g.rule_version_id for g in groups] == sorted(by_version, key=str)


def test_a_query_reads_at_most_the_page_limit_plus_one() -> None:
    with pytest.raises(InvariantViolationError):
        ErrorReviewQuery(limit=202)
    with pytest.raises(InvariantViolationError):
        ErrorReviewQuery(limit=0)
    assert ErrorReviewQuery(limit=201).limit == 201


# ---------------------------------------------------------------- the decisions


def test_confirming_needs_the_version_that_corrects_the_reported_one(
    store: MemoryKnowledgeStore, clock: Clock
) -> None:
    old, new, other = versions(store)
    review = IntakeErrorReport(store, clock).run(TENANT, payload(old)).review
    decide = DecideErrorReview(store, clock)

    with pytest.raises(CorrectingVersionRequiredError):
        decide.run(review.report_id, ErrorOutcome.CONFIRMED, by=ANALYST)
    with pytest.raises(UnknownRuleVersionError):
        decide.run(
            review.report_id,
            ErrorOutcome.CONFIRMED,
            by=ANALYST,
            correcting_rule_version_id=RuleVersionId.new(),
        )
    with pytest.raises(CorrectingVersionRequiredError, match="no corrects relation"):
        decide.run(
            review.report_id, ErrorOutcome.CONFIRMED, by=ANALYST, correcting_rule_version_id=new
        )
    relate(store, other, old)
    with pytest.raises(CorrectingVersionRequiredError):
        # Another version's relation to the reported one does not count.
        decide.run(
            review.report_id, ErrorOutcome.CONFIRMED, by=ANALYST, correcting_rule_version_id=new
        )
    assert store.events() == []
    assert store.audit_entries() == []
    assert store.error_reviews()[0].is_open

    relate(store, new, old)
    decided = decide.run(
        review.report_id,
        ErrorOutcome.CONFIRMED,
        by=ANALYST,
        notes="Example: version 2 moves the date to the 25th.",
        correcting_rule_version_id=new,
    )

    assert (decided.status, decided.decided_by, decided.correcting_rule_version_id) == (
        ErrorReviewStatus.CONFIRMED,
        ANALYST,
        new,
    )
    assert decided.decided_at == clock.now
    assert store.error_reviews() == [decided]
    (event,) = store.events()
    assert isinstance(event, ErrorReportDecided)
    assert (event.tenant_id, event.partition_key) == (TENANT, str(TENANT))
    assert payload_of(event) == {
        "report_id": str(review.report_id),
        "rule_version_id": str(old),
        "outcome": "confirmed",
        "notes": "Example: version 2 moves the date to the 25th.",
        "correcting_rule_version_id": str(new),
        "decided_at": decided.decided_at.isoformat(),
    }
    (entry,) = store.audit_entries(DECIDED_ACTION)
    assert (entry.subject_type, entry.subject_id, entry.tenant_id) == (
        "error_report",
        str(review.report_id),
        None,
    )
    assert entry.actor.id == str(ANALYST)
    assert (entry.before, entry.after) == (
        {"status": "open"},
        {
            "status": "confirmed",
            "rule_version_id": str(old),
            "correcting_rule_version_id": str(new),
            "tenant_erased": False,
        },
    )
    assert entry.reason == "Example: version 2 moves the date to the 25th."


def test_a_rejection_keeps_the_notes_and_a_decision_is_final(
    store: MemoryKnowledgeStore, clock: Clock
) -> None:
    old, new, _ = versions(store)
    review = IntakeErrorReport(store, clock).run(TENANT, payload(old)).review
    decide = DecideErrorReview(store, clock)

    rejected = decide.run(
        review.report_id, ErrorOutcome.REJECTED, by=REVIEWER, notes="Example: the date stands."
    )

    assert (rejected.status, rejected.decided_by, rejected.notes) == (
        ErrorReviewStatus.REJECTED,
        REVIEWER,
        "Example: the date stands.",
    )
    assert rejected.correcting_rule_version_id is None
    (event,) = store.events()
    assert isinstance(event, ErrorReportDecided)
    assert (event.outcome, event.correcting_rule_version_id) == (ErrorOutcome.REJECTED, None)
    with pytest.raises(ErrorReviewClosedError):
        decide.run(
            review.report_id, ErrorOutcome.CONFIRMED, by=ANALYST, correcting_rule_version_id=new
        )
    with pytest.raises(ErrorReviewNotFoundError):
        decide.run(uuid4(), ErrorOutcome.REJECTED, by=ANALYST)
    assert len(store.events()) == 1
    assert len(store.audit_entries(DECIDED_ACTION)) == 1


def test_an_erased_tenants_review_is_decided_for_the_record_without_an_event(
    store: MemoryKnowledgeStore, clock: Clock
) -> None:
    old, _, _ = versions(store)
    review = IntakeErrorReport(store, clock).run(TENANT, payload(old)).review
    assert store.erase_error_reviews(TENANT) == 1
    assert store.erase_error_reviews(TENANT) == 0

    decided = DecideErrorReview(store, clock).run(
        review.report_id, ErrorOutcome.REJECTED, by=ANALYST, notes="n"
    )

    assert (decided.tenant_id, decided.description_masked, decided.status) == (
        None,
        "",
        ErrorReviewStatus.REJECTED,
    )
    assert store.events() == [], "there is no tenant to tell"
    (entry,) = store.audit_entries(DECIDED_ACTION)
    assert entry.after is not None
    assert entry.after["tenant_erased"] is True


# ---------------------------------------------------------------- the domain's own rules


def review_of(**overrides: Any) -> ErrorReview:
    report_id = uuid4()
    values: dict[str, Any] = {
        "review_id": review_id_for(report_id),
        "report_id": report_id,
        "tenant_id": TENANT,
        "obligation_id": ObligationId.new(),
        "rule_version_id": RuleVersionId.new(),
        "category": ErrorCategory.OTHER,
        "description_masked": "Example: something else is wrong.",
        "received_at": START,
    }
    values.update(overrides)
    return ErrorReview(**values)


def test_a_review_is_decided_exactly_once_and_only_a_confirmation_names_a_version() -> None:
    review = review_of()
    with pytest.raises(InvariantViolationError):
        review_of(status=ErrorReviewStatus.CONFIRMED, decided_by=ANALYST, decided_at=START)
    with pytest.raises(InvariantViolationError):
        review_of(status=ErrorReviewStatus.REJECTED, decided_at=START)
    with pytest.raises(InvariantViolationError):
        review_of(correcting_rule_version_id=RuleVersionId.new())
    with pytest.raises(InvariantViolationError):
        review_of(description_masked="x" * 2001)
    with pytest.raises(CorrectingVersionRequiredError):
        review.decide(ErrorOutcome.CONFIRMED, by=ANALYST, at=START)
    rejected = review.decide(
        ErrorOutcome.REJECTED,
        by=ANALYST,
        at=START,
        correcting_rule_version_id=RuleVersionId.new(),
    )
    assert rejected.correcting_rule_version_id is None, "a rejection names no version"
    with pytest.raises(ErrorReviewClosedError):
        rejected.decide(ErrorOutcome.REJECTED, by=ANALYST, at=START)
    erased = rejected.erased()
    assert (erased.tenant_id, erased.description_masked, erased.status) == (
        None,
        "",
        ErrorReviewStatus.REJECTED,
    )
    assert review_id_for(review.report_id) == review.review_id, "derived, so a replay lands"


# ---------------------------------------------------------------- over HTTP


def app_in(mode: AuthMode = "header") -> FastAPI:
    return build_app(
        rulebook_settings(rulebook_publish_enabled=True, **ISSUER.settings_overrides(mode))
    )


@pytest.fixture
def api() -> Iterator[tuple[TestClient, MemoryKnowledgeStore]]:
    app = app_in()
    with TestClient(app) as client:
        store = app.state.wiring.unit_of_work
        assert isinstance(store, MemoryKnowledgeStore)
        yield client, store


def test_the_routes_list_the_queue_and_decide_a_report_once(
    api: tuple[TestClient, MemoryKnowledgeStore],
) -> None:
    client, store = api
    old, new, other = versions(store)
    intake = IntakeErrorReport(store)
    ours = intake.run(TENANT, payload(old)).review
    theirs = intake.run(OTHER_TENANT, payload(other, category="citation")).review

    listed = client.get(BASE, params={"limit": 1})
    assert listed.status_code == 200, listed.text
    page = listed.json()
    assert len(page["items"]) == 1
    assert page["next_cursor"]
    assert {g["rule_version_id"]: g["open"] for g in page["groups"]} == {
        str(old): 1,
        str(other): 1,
    }
    rest = client.get(BASE, params={"limit": 1, "cursor": page["next_cursor"]})
    assert rest.status_code == 200, rest.text
    assert rest.json()["next_cursor"] is None
    seen = [item["report_id"] for item in page["items"] + rest.json()["items"]]
    assert sorted(seen) == sorted(str(r.report_id) for r in (ours, theirs))
    item = next(
        i for i in page["items"] + rest.json()["items"] if i["report_id"] == str(ours.report_id)
    )
    assert (item["tenant_id"], item["status"], item["category"]) == (
        str(TENANT),
        "open",
        "due_date",
    )
    assert item["description"] == ours.description_masked
    assert item["decided_by"] is None
    assert item["correcting_rule_version_id"] is None
    by_version = client.get(BASE, params={"rule_version_id": str(other)})
    assert [i["report_id"] for i in by_version.json()["items"]] == [str(theirs.report_id)]

    missing = client.post(
        f"{BASE}/{uuid4()}/decision",
        json={"actor_id": str(ANALYST), "decision": "rejected"},
        headers=REVIEW,
    )
    assert (missing.status_code, problem(missing)) == (404, "rulebook-error-review-not-found")
    unnamed = client.post(
        f"{BASE}/{ours.report_id}/decision",
        json={"actor_id": str(ANALYST), "decision": "confirmed"},
        headers=REVIEW,
    )
    assert (unnamed.status_code, problem(unnamed)) == (422, "rulebook-correcting-version-required")
    unknown = client.post(
        f"{BASE}/{ours.report_id}/decision",
        json={
            "actor_id": str(ANALYST),
            "decision": "confirmed",
            "correcting_rule_version_id": str(uuid4()),
        },
        headers=REVIEW,
    )
    assert (unknown.status_code, problem(unknown)) == (404, UnknownRuleVersionError.type_slug)
    no_token = client.post(
        f"{BASE}/{ours.report_id}/decision", json={"actor_id": str(ANALYST), "decision": "rejected"}
    )
    assert no_token.status_code == 401, no_token.text

    relate(store, new, old)
    confirmed = client.post(
        f"{BASE}/{ours.report_id}/decision",
        json={
            "actor_id": str(ANALYST),
            "decision": "confirmed",
            "notes": "Example: version 2 corrects the date.",
            "correcting_rule_version_id": str(new),
        },
        headers=REVIEW,
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert (body["status"], body["decided_by"], body["correcting_rule_version_id"]) == (
        "confirmed",
        str(ANALYST),
        str(new),
    )
    assert body["decided_at"] is not None
    assert body["notes"] == "Example: version 2 corrects the date."
    again = client.post(
        f"{BASE}/{ours.report_id}/decision",
        json={"actor_id": str(ANALYST), "decision": "rejected"},
        headers=REVIEW,
    )
    assert (again.status_code, problem(again)) == (409, "rulebook-error-review-closed")
    (group,) = client.get(BASE).json()["groups"]
    assert datetime.fromisoformat(group.pop("oldest_received_at")) == theirs.received_at
    assert group == {
        "rule_version_id": str(other),
        "rule_key": QUARTERLY,
        "version": 1,
        "title": "Quarterly statement (synthetic)",
        "open": 1,
    }
    decided = client.get(BASE, params={"status": "confirmed"}).json()["items"]
    assert [i["report_id"] for i in decided] == [str(ours.report_id)]
    (event,) = store.events()
    assert isinstance(event, ErrorReportDecided)
    assert event.tenant_id == TENANT


def test_in_token_mode_the_token_names_the_analyst_and_an_owner_is_refused() -> None:
    app = app_in("token")
    with TestClient(app) as client:
        store = app.state.wiring.unit_of_work
        assert isinstance(store, MemoryKnowledgeStore)
        old, _, _ = versions(store)
        review = IntakeErrorReport(store).run(TENANT, payload(old)).review

        assert client.get(BASE, headers=OWNER_BEARER).status_code == 403
        refused = client.post(
            f"{BASE}/{review.report_id}/decision",
            json={"actor_id": str(REVIEWER), "decision": "rejected"},
            headers=OWNER_BEARER,
        )
        assert refused.status_code == 403, refused.text
        assert client.get(BASE, headers=ANALYST_BEARER).status_code == 200

        decided = client.post(
            f"{BASE}/{review.report_id}/decision",
            json={"actor_id": str(REVIEWER), "decision": "rejected", "notes": "n"},
            headers=ANALYST_BEARER,
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["decided_by"] == str(ANALYST), "the token wins over the body"
        (entry,) = store.audit_entries(DECIDED_ACTION)
        assert entry.actor.id == str(ANALYST)
