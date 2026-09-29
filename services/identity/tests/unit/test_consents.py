import threading
from datetime import UTC, datetime

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ConsentId, TenantId, UserId
from identity.application.consents import ConsentStatus, RecordConsent
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource
from identity.domain.errors import NoticeVersionRequiredError
from identity.infrastructure.memory import MemoryStore

TENANT = TenantId.new()
OTHER = TenantId.new()
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)
API = ConsentSource.API


def test_grant_then_withdraw_is_append_only_and_the_latest_wins() -> None:
    store = MemoryStore()
    record = RecordConsent(store, clock=lambda: NOW)
    status = ConsentStatus(store)
    granted = record.run(
        TENANT,
        "user-1",
        ConsentPurpose.WHATSAPP_REMINDERS,
        granted=True,
        source=ConsentSource.WEB_ONBOARDING,
        notice_version="0.1-draft",
        evidence="checkbox: Send me GST reminders",
        recorded_by=UserId.new(),
    )
    assert granted.notice_version == "0.1-draft"
    summary = status.run(TENANT, "user-1")
    assert summary.granted(ConsentPurpose.WHATSAPP_REMINDERS)
    record.run(
        TENANT,
        "user-1",
        ConsentPurpose.WHATSAPP_REMINDERS,
        granted=False,
        source=ConsentSource.WHATSAPP_KEYWORD,
        evidence="STOP",
    )
    summary = status.run(TENANT, "user-1")
    assert not summary.granted(ConsentPurpose.WHATSAPP_REMINDERS)
    assert len(summary.history) == 2
    assert summary.states[0].source is ConsentSource.WHATSAPP_KEYWORD
    assert not summary.granted(ConsentPurpose.TERMS)
    assert status.run(OTHER, "user-1").history == ()


def test_overlapping_units_of_two_tenants_keep_both_records() -> None:
    """The second unit waits for the first to commit instead of starting from the same copy of
    the store and dropping the other tenant's record."""
    store = MemoryStore()
    done = threading.Event()

    def withdraw_for_other() -> None:
        RecordConsent(store, clock=lambda: NOW).run(
            OTHER, "user-2", ConsentPurpose.ANALYTICS, granted=False, source=ConsentSource.API
        )
        done.set()

    with store(TENANT) as uow:
        uow.consents.add(
            ConsentRecord(
                ConsentId.new(), TENANT, "user-1", ConsentPurpose.ANALYTICS, False, API, NOW
            )
        )
        thread = threading.Thread(target=withdraw_for_other)
        thread.start()
        assert not done.wait(0.05), "a second unit of work ran inside the first"
    thread.join(timeout=5)
    assert done.is_set()
    status = ConsentStatus(store)
    assert len(status.run(TENANT, "user-1").history) == 1
    assert len(status.run(OTHER, "user-2").history) == 1


def test_granting_needs_the_notice_version() -> None:
    record = RecordConsent(MemoryStore())
    with pytest.raises(NoticeVersionRequiredError, match="terms"):
        record.run(TENANT, "u", ConsentPurpose.TERMS, granted=True, source=ConsentSource.API)
    withdrawal = record.run(
        TENANT, "u", ConsentPurpose.TERMS, granted=False, source=ConsentSource.API
    )
    assert withdrawal.notice_version == ""


def test_record_invariants() -> None:
    with pytest.raises(InvariantViolationError):
        ConsentRecord(
            ConsentId.new(), TENANT, "", ConsentPurpose.TERMS, True, ConsentSource.API, NOW
        )
