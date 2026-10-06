"""A classification's route, its status, the rule kinds and a person's triage."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from domain_kernel.documents import DocumentType
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import DocumentId
from pipeline.domain.classification import (
    DETECTOR,
    MAX_REASON_CHARS,
    TRIAGE,
    Classification,
    Relevance,
    Route,
    TypeConfidence,
    extracts_rules,
    reasons_of,
    route_of,
    status_after,
)
from pipeline.domain.raw_documents import DocumentStatus
from pipeline.domain.tasks import TaskId

NOW = datetime(2026, 10, 6, 6, 0, tzinfo=UTC)
DOCUMENT = DocumentId(UUID(int=7))
ANALYST = UUID(int=42)


def classification(**overrides: object) -> Classification:
    values: dict[str, object] = {
        "document_id": DOCUMENT,
        "doc_type": DocumentType.NOTIFICATION,
        "relevance": Relevance.RELEVANT,
        "confidence": TypeConfidence.CERTAIN,
        "reasons": ("its opening names it a notification",),
        "classified_at": NOW,
    }
    values.update(overrides)
    return Classification(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("doc_type", "relevance", "confidence", "route", "status"),
    [
        (
            DocumentType.NOTIFICATION,
            Relevance.RELEVANT,
            TypeConfidence.CERTAIN,
            Route.EXTRACT,
            DocumentStatus.CLASSIFIED,
        ),
        (
            DocumentType.CIRCULAR,
            Relevance.RELEVANT,
            TypeConfidence.DEFAULT,
            Route.EXTRACT,
            DocumentStatus.CLASSIFIED,
        ),
        (
            DocumentType.ACT_AMENDMENT,
            Relevance.RELEVANT,
            TypeConfidence.CERTAIN,
            Route.EXTRACT,
            DocumentStatus.CLASSIFIED,
        ),
        (
            DocumentType.PRESS_RELEASE,
            Relevance.RELEVANT,
            TypeConfidence.CERTAIN,
            Route.REFERENCE,
            DocumentStatus.REFERENCE,
        ),
        (
            DocumentType.STATUTE,
            Relevance.RELEVANT,
            TypeConfidence.CERTAIN,
            Route.REFERENCE,
            DocumentStatus.REFERENCE,
        ),
        (
            DocumentType.NOTIFICATION,
            Relevance.RELEVANT,
            TypeConfidence.CONFLICT,
            Route.TRIAGE,
            DocumentStatus.TRIAGE,
        ),
        (
            DocumentType.NOTIFICATION,
            Relevance.IRRELEVANT,
            TypeConfidence.CONFLICT,
            Route.IRRELEVANT,
            DocumentStatus.IRRELEVANT,
        ),
    ],
)
def test_the_route_and_status_follow_from_the_classification(
    doc_type: DocumentType,
    relevance: Relevance,
    confidence: TypeConfidence,
    route: Route,
    status: DocumentStatus,
) -> None:
    assert route_of(doc_type, relevance, confidence) is route
    assert route.status is status
    found = classification(doc_type=doc_type, relevance=relevance, confidence=confidence)
    assert found.route is route
    assert route.stops is (route in (Route.TRIAGE, Route.IRRELEVANT))


def test_an_extracted_document_classified_again_stays_extracted_on_its_way_there() -> None:
    assert status_after(Route.EXTRACT, extracted=True) is DocumentStatus.EXTRACTED
    assert status_after(Route.EXTRACT, extracted=False) is DocumentStatus.CLASSIFIED
    for route in (Route.REFERENCE, Route.IRRELEVANT, Route.TRIAGE):
        assert status_after(route, extracted=True) is route.status, route


def test_rules_are_extracted_from_notifications_circulars_and_act_amendments_only() -> None:
    assert [kind.value for kind in DocumentType if extracts_rules(kind)] == [
        "notification",
        "circular",
        "act_amendment",
    ]
    assert not extracts_rules("press_release")


def test_a_classification_gives_its_reasons_and_only_a_triage_is_a_persons() -> None:
    with pytest.raises(InvariantViolationError, match="reasons"):
        classification(reasons=())
    with pytest.raises(InvariantViolationError, match="at most"):
        classification(reasons=("x" * (MAX_REASON_CHARS + 1),))
    with pytest.raises(InvariantViolationError, match="decided by a person"):
        classification(decided_by=ANALYST)
    assert classification().classifier == DETECTOR
    assert reasons_of(("  first ", "", "second")) == ("first", "second")


def test_a_triage_is_certain_with_the_analysts_reason() -> None:
    task = TaskId(UUID(int=9))
    triaged = Classification.triaged(
        DOCUMENT,
        relevance=Relevance.RELEVANT,
        doc_type=DocumentType.CIRCULAR,
        by=ANALYST,
        task_id=task,
        at=NOW,
        reason="It clarifies the law: a circular",
    )
    assert (triaged.classifier, triaged.confidence, triaged.route) == (
        TRIAGE,
        TypeConfidence.CERTAIN,
        Route.EXTRACT,
    )
    assert triaged.reasons == (
        "an analyst triaged it as a circular",
        "It clarifies the law: a circular",
    )
    assert (triaged.decided_by, triaged.task_id) == (ANALYST, task)
    aside = Classification.triaged(
        DOCUMENT,
        relevance=Relevance.IRRELEVANT,
        doc_type=DocumentType.NOTIFICATION,
        by=None,
        task_id=task,
        at=NOW,
        reason="A portal manual",
    )
    assert aside.route is Route.IRRELEVANT
    assert aside.reasons[0] == "an analyst triaged it as no regulatory document"


def test_a_status_is_unparsed_until_a_parse_is_recorded() -> None:
    assert [status.value for status in DocumentStatus if status.unparsed] == [
        "discovered",
        "failed",
    ]
