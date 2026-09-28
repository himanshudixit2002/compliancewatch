"""Read models: the due day in India, open obligations, how a clause and a rule are named."""

from datetime import UTC, date, datetime
from uuid import UUID

from domain_kernel.ids import BusinessId, ClauseId, DocumentId, ObligationId, RuleVersionId
from domain_kernel.status import ObligationStatus
from qa.domain.prompt import PromptText
from qa.domain.records import ClauseRecord, ObligationRecord, RuleVersion


def obligation(status: ObligationStatus, due_at: datetime | None) -> ObligationRecord:
    return ObligationRecord(
        obligation_id=ObligationId(UUID(int=1)),
        business_id=BusinessId(UUID(int=2)),
        rule_version_id=RuleVersionId(UUID(int=3)),
        title="File GSTR-3B for the month (2026-03)",
        status=status,
        period_label="2026-03",
        due_at=due_at,
    )


def test_the_due_day_is_the_day_in_india() -> None:
    end_of_day = datetime(2026, 4, 20, 18, 29, 59, tzinfo=UTC)
    assert obligation(ObligationStatus.OPEN, end_of_day).due_on == date(2026, 4, 20)
    assert obligation(ObligationStatus.OPEN, None).due_on is None


def test_open_and_in_progress_are_open() -> None:
    assert obligation(ObligationStatus.OPEN, None).is_open
    assert obligation(ObligationStatus.IN_PROGRESS, None).is_open
    assert not obligation(ObligationStatus.DONE, None).is_open


def test_names() -> None:
    clause = ClauseRecord(ClauseId(UUID(int=4)), DocumentId(UUID(int=5)), "en.p1", "t", title="T")
    assert clause.source == "T"
    numbered = ClauseRecord(
        ClauseId(UUID(int=4)),
        DocumentId(UUID(int=5)),
        "en.p1",
        "t",
        external_ref="01/2026",
        title="T",
    )
    assert numbered.source == "01/2026"
    rule = RuleVersion(RuleVersionId(UUID(int=6)), "annual", "cbic", 2, "File", date(2026, 4, 1))
    assert rule.label == "rule annual version 2"


def test_a_prompt_is_referenced_by_name_and_version() -> None:
    assert PromptText("qa.plan", "1", "ai-platform", "text").ref == "qa.plan@1"
