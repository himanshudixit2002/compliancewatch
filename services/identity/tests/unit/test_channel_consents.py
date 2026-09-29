import threading
from datetime import UTC, datetime, timedelta

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ConsentId
from identity.application.channel_consents import ChannelConsentStatus, RecordChannelConsent
from identity.domain.channel_consent import ChannelConsentRecord, ConsentChannel, channel_subject
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.domain.errors import (
    ChannelPurposeInvalidError,
    ChannelSubjectInvalidError,
    NoticeVersionRequiredError,
)
from identity.infrastructure.memory import MemoryChannelStore

NOW = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
NUMBER = "919876543210"
WHATSAPP = ConsentChannel.WHATSAPP
REMINDERS = ConsentPurpose.WHATSAPP_REMINDERS
KEYWORD = ConsentSource.WHATSAPP_KEYWORD
NOTICE = "whatsapp-consent 0.1-draft"


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        self.now += timedelta(minutes=1)
        return self.now


def test_grant_then_withdraw_and_the_latest_record_per_purpose_wins() -> None:
    store = MemoryChannelStore()
    record = RecordChannelConsent(store, clock=Clock())
    status = ChannelConsentStatus(store)
    granted = record.run(
        WHATSAPP,
        "+" + NUMBER,
        REMINDERS,
        granted=True,
        source=KEYWORD,
        notice_version=f" {NOTICE} ",
        evidence="keyword START in WhatsApp message wamid.1",
        message_id="wamid.1",
    )
    assert granted.created
    assert granted.record.subject == NUMBER
    assert granted.record.notice_version == NOTICE
    assert status.run(WHATSAPP, NUMBER).granted(REMINDERS)

    withdrawn = record.run(
        WHATSAPP, NUMBER, REMINDERS, granted=False, source=KEYWORD, message_id="wamid.2"
    )
    assert withdrawn.created
    summary = status.run(WHATSAPP, "+" + NUMBER)
    assert summary.subject == NUMBER
    assert not summary.granted(REMINDERS)
    assert [r.message_id for r in summary.history] == ["wamid.1", "wamid.2"]
    (state,) = summary.states
    assert (state.granted, state.since, state.notice_version) == (
        False,
        withdrawn.record.recorded_at,
        "",
    )
    assert status.run(WHATSAPP, "919999999999").history == ()


def test_the_same_message_is_recorded_once() -> None:
    store = MemoryChannelStore()
    record = RecordChannelConsent(store, clock=Clock())
    first = record.run(
        WHATSAPP,
        NUMBER,
        REMINDERS,
        granted=True,
        source=KEYWORD,
        notice_version=NOTICE,
        message_id="wamid.1",
    )
    again = record.run(
        WHATSAPP,
        NUMBER,
        REMINDERS,
        granted=True,
        source=KEYWORD,
        notice_version=NOTICE,
        message_id=" wamid.1 ",
    )
    assert not again.created
    assert again.record == first.record
    without_id = [
        record.run(WHATSAPP, NUMBER, REMINDERS, granted=False, source=KEYWORD) for _ in range(2)
    ]
    assert all(outcome.created for outcome in without_id)
    assert len(store.records) == 3


def test_a_grant_needs_the_notice_version_and_nothing_is_stored() -> None:
    store = MemoryChannelStore()
    with pytest.raises(NoticeVersionRequiredError, match="whatsapp_reminders"):
        RecordChannelConsent(store).run(
            WHATSAPP, NUMBER, REMINDERS, granted=True, source=KEYWORD, notice_version=" "
        )
    assert store.records == []


@pytest.mark.parametrize("subject", ["", "12345", "+0919876543210", "91 98765 43210", "9" * 16])
def test_a_subject_that_is_not_a_phone_number_is_refused(subject: str) -> None:
    with pytest.raises(ChannelSubjectInvalidError):
        RecordChannelConsent(MemoryChannelStore()).run(
            WHATSAPP, subject, REMINDERS, granted=False, source=KEYWORD
        )
    with pytest.raises(ChannelSubjectInvalidError):
        ChannelConsentStatus(MemoryChannelStore()).run(WHATSAPP, subject)


def test_whatsapp_records_only_whatsapp_reminders() -> None:
    with pytest.raises(ChannelPurposeInvalidError, match="it records whatsapp_reminders"):
        RecordChannelConsent(MemoryChannelStore()).run(
            WHATSAPP, NUMBER, ConsentPurpose.TERMS, granted=False, source=KEYWORD
        )


def test_the_memory_store_keeps_nothing_from_a_failed_unit_of_work() -> None:
    store = MemoryChannelStore()
    record = ChannelConsentRecord(
        ConsentId.new(), WHATSAPP, NUMBER, REMINDERS, False, KEYWORD, NOW, message_id="m"
    )

    def add_then_fail() -> None:
        with store() as uow:
            uow.channel_consents.add(record)
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        add_then_fail()
    assert store.records == []
    with store() as uow:
        assert uow.channel_consents.by_message(WHATSAPP, "") is None


def test_overlapping_units_of_work_keep_both_records() -> None:
    """The second unit waits for the first to commit instead of starting from the same copy of
    the records and dropping the first one."""
    store = MemoryChannelStore()
    done = threading.Event()

    def record_second() -> None:
        RecordChannelConsent(store, clock=Clock()).run(
            WHATSAPP, NUMBER, REMINDERS, granted=False, source=KEYWORD, message_id="wamid.2"
        )
        done.set()

    with store() as uow:
        uow.channel_consents.add(
            ChannelConsentRecord(
                ConsentId.new(), WHATSAPP, NUMBER, REMINDERS, False, KEYWORD, NOW, message_id="m"
            )
        )
        thread = threading.Thread(target=record_second)
        thread.start()
        assert not done.wait(0.05), "a second unit of work ran inside the first"
    thread.join(timeout=5)
    assert done.is_set()
    assert [record.message_id for record in store.records] == ["m", "wamid.2"]


def test_record_invariants() -> None:
    def build(**changes: object) -> ChannelConsentRecord:
        values: dict[str, object] = {
            "id": ConsentId.new(),
            "channel": WHATSAPP,
            "subject": NUMBER,
            "purpose": REMINDERS,
            "granted": True,
            "source": KEYWORD,
            "recorded_at": NOW,
            "notice_version": NOTICE,
        }
        values.update(changes)
        return ChannelConsentRecord(**values)  # type: ignore[arg-type]

    assert build().subject == NUMBER
    assert channel_subject(WHATSAPP, "+" + NUMBER) == NUMBER
    with pytest.raises(InvariantViolationError, match="without the plus"):
        build(subject="+" + NUMBER)
    with pytest.raises(InvariantViolationError, match="source api"):
        build(source=ConsentSource.API)
    with pytest.raises(InvariantViolationError, match="notice_version"):
        build(notice_version="")
    with pytest.raises(InvariantViolationError, match="timezone-aware"):
        build(recorded_at=datetime(2026, 9, 29))
    with pytest.raises(InvariantViolationError, match="at most 255"):
        build(message_id="m" * 256)
    with pytest.raises(InvariantViolationError, match="whitespace"):
        build(message_id=" m")
    with pytest.raises(ChannelPurposeInvalidError):
        build(purpose=ConsentPurpose.ANALYTICS)
