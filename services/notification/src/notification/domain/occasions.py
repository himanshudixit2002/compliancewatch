"""Why a notification goes out, and the key that makes it go out once.

An occasion is the thing a person is told about: a change card for a rule version that now
applies, a reminder before a due date, a closure, a reschedule, or a manual send through the
API. ``dedupe_key`` turns the occasion, the business, the recipient and the channel into the
key the store keeps unique, so a redelivered event or a repeated call makes no second message:

- change card: the guide's section 9 key, ``DedupeKey.for_notification(rule_version_id,
  business_id, channel)``, taken per recipient. It names the rule version, not the obligation,
  so the later periods of a recurring rule do not repeat the card;
- reminder: one per obligation, reminder number, recipient and channel;
- closure: one per obligation, recipient and channel;
- reschedule: one per obligation and new due date, recipient and channel;
- manual: one per obligation, business, channel and template, as ``POST /send`` has always
  keyed it, and per recipient when the send names one.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from domain_kernel._validation import require_aware, require_instance, require_int, require_text
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId
from notification.domain.ids import RecipientId


class OccasionKind(StrEnum):
    CHANGE_CARD = "change_card"
    REMINDER = "reminder"
    CLOSURE = "closure"
    RESCHEDULE = "reschedule"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Occasion:
    """What one notification is about. Each kind carries the one detail its key needs; the
    constructors below build the valid shapes."""

    kind: OccasionKind
    obligation_id: ObligationId
    rule_version_id: RuleVersionId | None = None
    """The change card's rule version."""
    reminder_index: int | None = None
    """The reminder's number: 1 for the first reminder of an obligation, and so on."""
    new_due_at: datetime | None = None
    """The reschedule's new due date."""
    template_key: str = ""
    """The manual send's template."""

    def __post_init__(self) -> None:
        require_instance(self.kind, OccasionKind, "kind")
        require_instance(self.obligation_id, ObligationId, "obligation_id")
        needs = {
            OccasionKind.CHANGE_CARD: self.rule_version_id is not None,
            OccasionKind.REMINDER: self.reminder_index is not None,
            OccasionKind.RESCHEDULE: self.new_due_at is not None,
            OccasionKind.MANUAL: bool(self.template_key),
        }
        if not needs.get(self.kind, True):
            raise InvariantViolationError(f"a {self.kind.value} occasion misses its detail")
        if self.rule_version_id is not None:
            require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        if self.reminder_index is not None:
            require_int(self.reminder_index, "reminder_index", minimum=1)
        if self.new_due_at is not None:
            require_aware(self.new_due_at, "new_due_at")
        if self.template_key:
            require_text(self.template_key, "template_key")

    @classmethod
    def change_card(cls, obligation_id: ObligationId, rule_version_id: RuleVersionId) -> "Occasion":
        return cls(OccasionKind.CHANGE_CARD, obligation_id, rule_version_id=rule_version_id)

    @classmethod
    def reminder(cls, obligation_id: ObligationId, reminder_index: int) -> "Occasion":
        return cls(OccasionKind.REMINDER, obligation_id, reminder_index=reminder_index)

    @classmethod
    def closure(cls, obligation_id: ObligationId) -> "Occasion":
        return cls(OccasionKind.CLOSURE, obligation_id)

    @classmethod
    def reschedule(cls, obligation_id: ObligationId, new_due_at: datetime) -> "Occasion":
        return cls(OccasionKind.RESCHEDULE, obligation_id, new_due_at=new_due_at)

    @classmethod
    def manual(cls, obligation_id: ObligationId, template_key: str) -> "Occasion":
        return cls(OccasionKind.MANUAL, obligation_id, template_key=template_key)


def dedupe_key(
    occasion: Occasion,
    business_id: BusinessId,
    recipient_id: RecipientId | None,
    channel: Channel,
) -> DedupeKey:
    """The key of one occasion for one recipient on one channel.

    Every kind but the manual send needs a recipient: those notifications fan out to the
    business's recipients, and each of them gets one.
    """
    match occasion.kind:
        case OccasionKind.MANUAL:
            material = (
                f"{occasion.obligation_id}|{business_id}|{channel.value}|{occasion.template_key}"
            )
            if recipient_id is not None:
                material += f"|{recipient_id}"
            return _digest(material)
        case OccasionKind.CHANGE_CARD:
            recipient = _required(recipient_id, occasion)
            assert occasion.rule_version_id is not None
            card = DedupeKey.for_notification(occasion.rule_version_id, business_id, channel)
            return _digest(f"{card.value}|{recipient}")
        case OccasionKind.REMINDER:
            tail = _tail(business_id, _required(recipient_id, occasion), channel)
            return _digest(f"{occasion.obligation_id}|{occasion.reminder_index}|reminder|{tail}")
        case OccasionKind.CLOSURE:
            tail = _tail(business_id, _required(recipient_id, occasion), channel)
            return _digest(f"{occasion.obligation_id}|closed|{tail}")
        case OccasionKind.RESCHEDULE:
            tail = _tail(business_id, _required(recipient_id, occasion), channel)
            assert occasion.new_due_at is not None
            due = occasion.new_due_at.astimezone(UTC).isoformat()
            return _digest(f"{occasion.obligation_id}|rescheduled|{due}|{tail}")


def _required(recipient_id: RecipientId | None, occasion: Occasion) -> RecipientId:
    if recipient_id is None:
        raise InvariantViolationError(f"a {occasion.kind.value} key needs the recipient")
    return recipient_id


def _tail(business_id: BusinessId, recipient_id: RecipientId, channel: Channel) -> str:
    return f"{business_id}|{recipient_id}|{channel.value}"


def _digest(material: str) -> DedupeKey:
    return DedupeKey(hashlib.sha256(material.encode("utf-8")).hexdigest())
