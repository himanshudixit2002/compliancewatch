"""The golden obligation.* examples as notices, and what the service leaves alone."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from notification.domain.occasions import Occasion
from notification.infrastructure.events_in import MissingTenantError, notice_from
from py_common.events import EventMessage

EXAMPLES = Path(__file__).resolve().parents[4] / "packages" / "contracts" / "events" / "examples"
OBLIGATION = ObligationId(UUID("8c9d0e1f-2a3b-4c4d-9e5f-6a7b8c9d0e1f"))
BUSINESS = BusinessId(UUID("6a7b8c9d-0e1f-4a2b-9c3d-4e5f6a7b8c9d"))
RULE = "4e5f6a7b-8c9d-4e0f-9a1b-2c3d4e5f6a7b"


def example(topic: str, name: str, **payload: Any) -> EventMessage:
    data = json.loads((EXAMPLES / topic / f"{name}.json").read_text(encoding="utf-8"))
    data["payload"].update(payload)
    return EventMessage.model_validate(data)


def test_a_created_obligation_is_a_change_card_of_its_rule_version() -> None:
    message = example("obligation.created", "filing-with-due-date")
    notice = notice_from(message)
    assert notice is not None
    assert notice.tenant_id == TenantId(UUID("5b1f3d2e-7c4a-4e0b-9a6d-1f2e3d4c5b6a"))
    assert (notice.business_id, notice.template_key) == (BUSINESS, "change_card")
    assert notice.occasion == Occasion.change_card(OBLIGATION, RuleVersionId(UUID(RULE)))
    assert dict(notice.params) == {
        "title": "File GSTR-3B for September 2026",
        "steps": ["Reconcile ITC", "File on the GST portal"],
        "due_at": "2026-10-25T23:59:59+05:30",
        "rule_version_id": RULE,
    }
    no_deadline = notice_from(example("obligation.created", "no-deadline"))
    assert no_deadline is not None
    assert (no_deadline.params["due_at"], no_deadline.params["steps"]) == (None, [])


def test_a_due_soon_event_is_one_reminder_per_number() -> None:
    notice = notice_from(example("obligation.due_soon", "seven-days-first-reminder"))
    assert notice is not None
    assert notice.template_key == "obligation_due_soon"
    assert notice.occasion == Occasion.reminder(OBLIGATION, 1)
    assert (notice.params["days_left"], notice.params["reminder_index"]) == (7, 1)
    second = notice_from(
        example("obligation.due_soon", "seven-days-first-reminder", reminder_index=2)
    )
    assert second is not None
    assert second.occasion.reminder_index == 2


def test_a_reschedule_cites_the_version_that_changed_the_deadline() -> None:
    notice = notice_from(example("obligation.rescheduled", "deadline-extended-by-notification"))
    assert notice is not None
    assert notice.template_key == "obligation_deadline_extended"
    new_due = datetime(2026, 10, 25, 18, 29, 59, tzinfo=UTC)
    assert notice.occasion == Occasion.reschedule(OBLIGATION, new_due)
    assert notice.params["source_rule_version_id"] == RULE
    assert notice.params["rule_version_id"] == "5f6a7b8c-9d0e-4f1a-8b2c-3d4e5f6a7b8c"
    corrected = notice_from(
        example("obligation.rescheduled", "deadline-extended-by-notification", reason="corrected")
    )
    assert corrected is not None
    assert corrected.template_key == "obligation_corrected"
    assert notice_from(example("obligation.rescheduled", "manual")) is None


def test_closures_by_the_system_notify_and_the_users_own_do_not() -> None:
    notice = notice_from(example("obligation.closed", "profile-changed"))
    assert notice is not None
    assert (notice.template_key, notice.occasion) == (
        "obligation_closed",
        Occasion.closure(OBLIGATION),
    )
    assert notice.params["close_reason"] == "profile_changed"
    withdrawn = notice_from(
        example("obligation.closed", "profile-changed", reason="rule_withdrawn")
    )
    assert withdrawn is not None
    assert withdrawn.template_key == "obligation_withdrawn"
    assert notice_from(example("obligation.closed", "completed-by-user")) is None
    waived = example("obligation.closed", "completed-by-user", reason="waived_by_user")
    assert notice_from(waived) is None


def test_other_topics_are_left_alone_and_a_bad_event_raises() -> None:
    other = example("obligation.created", "filing-with-due-date").model_copy(
        update={"topic": "profile.updated"}
    )
    assert notice_from(other) is None
    no_tenant = example("obligation.created", "filing-with-due-date").model_copy(
        update={"tenant_id": None}
    )
    with pytest.raises(MissingTenantError):
        notice_from(no_tenant)
    broken = example("obligation.created", "filing-with-due-date", title="")
    with pytest.raises(ValidationError):
        notice_from(broken)
