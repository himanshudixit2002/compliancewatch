"""What an obligation event tells the service to send.

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

from domain_kernel._validation import freeze_mapping, require_instance, require_text
from domain_kernel.ids import BusinessId, TenantId
from notification.domain.occasions import Occasion


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
