"""What an obligation event tells the service to send, and whether it sends anything.

``EVENT_ROUTES`` maps each obligation event, by topic and reason, to the template it sends and
the occasion that keys it, or to None when it sends nothing. The deadline changes reuse the
templates ``templates.CHANGE_TEMPLATES`` names (ADR-015):

- ``obligation.created``: ``change_card`` (a rule now applies);
- ``obligation.due_soon``: ``obligation_due_soon``, one per reminder number;
- ``obligation.rescheduled``: ``obligation_deadline_extended`` or ``obligation_corrected``;
  a manual reschedule sends nothing;
- ``obligation.closed``: ``obligation_withdrawn`` when the rule was withdrawn,
  ``obligation_closed`` when the business profile changed or a newer rule version replaced the
  rule; the user's own completion or waiver sends nothing.

``ObligationNotice`` is one event as the service acts on it: the tenant and the business whose
recipients hear about it, the occasion (which also makes each recipient's dedupe key), the
template, and what the event says, kept as the notification's values until it goes out:

- ``title``, ``steps`` (a list) and ``due_at`` (ISO 8601, or None for a duty without a date);
- ``previous_due_at`` and ``new_due_at`` for a reschedule;
- ``closed_at`` and ``close_reason`` for a closure;
- ``rule_version_id``: the rule version whose published facts fill the message, and
  ``source_rule_version_id``: the one whose source a deadline change cites, when another
  version changed it.

The dispatcher turns these into the template's values when it sends (``domain.values``).
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from domain_kernel._validation import freeze_mapping, require_instance, require_text
from domain_kernel.ids import BusinessId, TenantId
from notification.domain.occasions import Occasion, OccasionKind
from notification.domain.templates import (
    CHANGE_CARD,
    CHANGE_TEMPLATES,
    CLOSED,
    DUE_SOON,
    SILENT_CHANGES,
)

CREATED_TOPIC = "obligation.created"
DUE_SOON_TOPIC = "obligation.due_soon"
RESCHEDULED_TOPIC = "obligation.rescheduled"
CLOSED_TOPIC = "obligation.closed"
TOPICS = (CREATED_TOPIC, DUE_SOON_TOPIC, RESCHEDULED_TOPIC, CLOSED_TOPIC)
"""The obligation topics the service consumes."""


@dataclass(frozen=True, slots=True)
class Route:
    template_key: str
    occasion: OccasionKind


_OCCASIONS = {RESCHEDULED_TOPIC: OccasionKind.RESCHEDULE, CLOSED_TOPIC: OccasionKind.CLOSURE}

EVENT_ROUTES: Mapping[tuple[str, str | None], Route | None] = MappingProxyType(
    {
        (CREATED_TOPIC, None): Route(CHANGE_CARD, OccasionKind.CHANGE_CARD),
        (DUE_SOON_TOPIC, None): Route(DUE_SOON, OccasionKind.REMINDER),
        **{
            (topic, reason): Route(key, _OCCASIONS[topic])
            for (topic, reason), key in CHANGE_TEMPLATES.items()
        },
        **dict.fromkeys(SILENT_CHANGES),
        (CLOSED_TOPIC, "profile_changed"): Route(CLOSED, OccasionKind.CLOSURE),
        (CLOSED_TOPIC, "rule_superseded"): Route(CLOSED, OccasionKind.CLOSURE),
        (CLOSED_TOPIC, "completed"): None,
        (CLOSED_TOPIC, "waived_by_user"): None,
    }
)
"""Each obligation event, by topic and reason (None for the topics without one), and what it
sends; None sends nothing."""


def route(topic: str, reason: str | None = None) -> Route | None:
    """The route of an event, or None when it sends nothing or is not one the table knows."""
    return EVENT_ROUTES.get((topic, reason))


@dataclass(frozen=True, slots=True, kw_only=True)
class ObligationNotice:
    tenant_id: TenantId
    business_id: BusinessId
    occasion: Occasion
    template_key: str
    params: Mapping[str, object] = field(default_factory=dict, hash=False)
    """The event's facts, as JSON values."""

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.business_id, BusinessId, "business_id")
        require_instance(self.occasion, Occasion, "occasion")
        require_text(self.template_key, "template_key")
        object.__setattr__(self, "params", freeze_mapping(self.params, "params"))
