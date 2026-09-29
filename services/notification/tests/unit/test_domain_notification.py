import math
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import DomainError, InvariantViolationError
from domain_kernel.ids import BusinessId, NotificationId, ObligationId, TenantId
from notification.domain import errors
from notification.domain.events import NotificationFailed, NotificationSent
from notification.domain.ids import DispatchId, RecipientId
from notification.domain.notification import DeliveryState, Notification
from notification.domain.occasions import OccasionKind
from notification.domain.policy import DEFAULT_RETRY_POLICY, RetryPolicy
from notification.domain.repository import WorkEntry, WorkKind
from notification.testing import NOON_IST

KEY = DedupeKey("a" * 64)
LATER = NOON_IST + timedelta(minutes=5)


def queued(**changes: object) -> Notification:
    values: dict[str, object] = {
        "tenant_id": TenantId.new(),
        "business_id": BusinessId.new(),
        "obligation_id": ObligationId.new(),
        "recipient_id": RecipientId.new(),
        "channel": Channel.WHATSAPP,
        "address": "+919876543210",
        "occasion": OccasionKind.REMINDER,
        "template_key": "obligation_due_soon",
        "language": "en",
        "params": {"title": "File GSTR-3B", "steps": ["Reconcile", "File"], "count": 2},
        "dedupe_key": KEY,
        "now": NOON_IST,
    }
    values.update(changes)
    return Notification.queue(**values)  # type: ignore[arg-type]


def test_a_queued_notification_is_available_now_or_when_asked() -> None:
    now = queued()
    assert (now.state, now.available_at, now.attempts) == (DeliveryState.QUEUED, NOON_IST, 0)
    assert now.is_pending
    digest = queued(available_at=LATER, digest=True)
    assert (digest.state, digest.available_at) == (DeliveryState.DIGEST_PENDING, LATER)
    assert WorkEntry.of(digest).kind is WorkKind.DIGEST_ITEM
    assert WorkEntry.of(now) == WorkEntry(now.id, now.tenant_id, WorkKind.ITEM, NOON_IST)


def test_sent_records_the_delivery_and_publishes_sent() -> None:
    item = queued()
    dispatch = DispatchId.new()
    sent, (event,) = item.sent(dispatch, "wamid.1", LATER)
    assert (sent.state, sent.attempts, sent.sent_at, sent.dispatch_id) == (
        DeliveryState.SENT,
        1,
        LATER,
        dispatch,
    )
    assert sent.provider_message_id == "wamid.1"
    assert isinstance(event, NotificationSent)
    assert (event.notification_id, event.tenant_id, event.dedupe_key) == (
        item.id,
        item.tenant_id,
        KEY.value,
    )
    assert event.provider_message_id == "wamid.1"
    assert sent.params == item.params
    with pytest.raises(InvariantViolationError):
        sent.sent(dispatch, "wamid.2", LATER)
    rendered, _ = item.sent(dispatch, "wamid.1", LATER, params={"title": "File", "link": "x"})
    assert dict(rendered.params) == {"title": "File", "link": "x"}


def test_retries_run_at_60_and_300_seconds_and_the_third_failure_is_final() -> None:
    item = queued()
    first, (event1,), retry1 = item.attempt_failed("503", NOON_IST, DEFAULT_RETRY_POLICY)
    assert retry1 == NOON_IST + timedelta(seconds=60)
    assert (first.state, first.attempts, first.available_at) == (DeliveryState.QUEUED, 1, retry1)
    assert isinstance(event1, NotificationFailed)
    assert (event1.attempts, event1.will_retry) == (1, True)

    second, (event2,), retry2 = first.attempt_failed("503", retry1, DEFAULT_RETRY_POLICY)
    assert retry2 == retry1 + timedelta(seconds=300)
    assert isinstance(event2, NotificationFailed)
    assert (event2.attempts, event2.will_retry) == (2, True)

    final, (event3,), retry3 = second.attempt_failed("503", retry2, DEFAULT_RETRY_POLICY)
    assert retry3 is None
    assert (final.state, final.attempts, final.failed_at, final.error) == (
        DeliveryState.FAILED,
        3,
        retry2,
        "503",
    )
    assert isinstance(event3, NotificationFailed)
    assert (event3.attempts, event3.will_retry) == (3, False)
    _, (with_fallback,), _ = second.attempt_failed(
        "503", retry2, DEFAULT_RETRY_POLICY, fallback=True
    )
    assert isinstance(with_fallback, NotificationFailed)
    assert with_fallback.will_retry, "a fallback address takes over"
    with pytest.raises(InvariantViolationError):
        final.attempt_failed("503", retry2, DEFAULT_RETRY_POLICY)


def test_a_failed_digest_item_stays_held_for_the_digest() -> None:
    item = queued(digest=True)
    failed, _, retry_at = item.attempt_failed("503", NOON_IST, DEFAULT_RETRY_POLICY)
    assert failed.state is DeliveryState.DIGEST_PENDING
    assert retry_at is not None


def test_defer_and_suppress() -> None:
    item = queued()
    deferred, events = item.defer(LATER, NOON_IST)
    assert (deferred.available_at, deferred.state, events) == (LATER, DeliveryState.QUEUED, ())
    suppressed, events = deferred.suppress("opted out", LATER)
    assert (suppressed.state, suppressed.error, events) == (
        DeliveryState.SUPPRESSED,
        "opted out",
        (),
    )
    assert not suppressed.is_pending
    with pytest.raises(InvariantViolationError):
        suppressed.defer(LATER, LATER)
    with pytest.raises(InvariantViolationError):
        deferred.defer(datetime(2026, 9, 29), NOON_IST)


def test_state_and_times_agree() -> None:
    item = queued()
    with pytest.raises(InvariantViolationError, match="sent_at"):
        replace(item, state=DeliveryState.DELIVERED)
    with pytest.raises(InvariantViolationError, match="failed_at"):
        replace(item, state=DeliveryState.FAILED)
    with pytest.raises(InvariantViolationError):
        replace(item, available_at=datetime(2026, 9, 29))
    with pytest.raises(InvariantViolationError):
        replace(item, attempts=-1)


@pytest.mark.parametrize(
    "params",
    [
        {"when": NOON_IST},
        {"ratio": math.nan},
        {"nested": {1: "x"}},
        {"list": [object()]},
    ],
)
def test_template_values_must_be_json(params: dict[str, object]) -> None:
    with pytest.raises(InvariantViolationError):
        queued(params=params)


def test_template_values_are_read_only() -> None:
    item = queued(params={"title": "x", "nested": {"a": [1, 2.5, None, True]}})
    with pytest.raises(TypeError):
        item.params["title"] = "y"  # type: ignore[index]


def test_ids_of_the_right_kind() -> None:
    with pytest.raises(InvariantViolationError):
        queued(recipient_id=NotificationId.new())
    with pytest.raises(InvariantViolationError):
        queued(fallback_of=RecipientId.new())


def test_retry_policy() -> None:
    policy = RetryPolicy(max_attempts=4, backoff_seconds=(10,))
    assert [policy.backoff(n).total_seconds() for n in (1, 2, 3)] == [10, 10, 10]
    assert not policy.is_final(3)
    assert policy.is_final(4)
    for bad in (
        {"max_attempts": 0},
        {"backoff_seconds": ()},
        {"backoff_seconds": (0,)},
    ):
        with pytest.raises(InvariantViolationError):
            RetryPolicy(**bad)
    with pytest.raises(InvariantViolationError):
        policy.backoff(0)


def test_every_error_has_its_own_slug_and_title() -> None:
    found = [
        value
        for value in vars(errors).values()
        if isinstance(value, type) and issubclass(value, DomainError) and value is not DomainError
    ]
    assert len({error.type_slug for error in found}) == len(found)
    assert len({error.title for error in found}) == len(found)
    assert all(error.type_slug.startswith("notification-") for error in found)
