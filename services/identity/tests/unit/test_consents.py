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
