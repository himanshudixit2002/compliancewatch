"""A CA firm's bulk notification of a change to its clients (guide use case 5; F9).

The firm names a published change, a rule version, and the client businesses it affects (the
ones the change's impact lists); each business gets the change card a rule that now applies
sends, through the same path as the card ``obligation.created`` makes:

1. With no unit of work open, the obligation service lists each business's open obligations of
   the version, as the firm's tenant reads them (``ObligationReader``). The card is about the
   first one due, and states its title, steps and due date, as the event would. A business with
   none is ``not_affected``: the change does not apply to it, asks nothing of it now (every
   obligation is closed), or the business is another tenant's, whose obligations row-level
   security hides.
2. In one unit of work of the tenant, each card is a notice of the routing table's route for
   ``obligation.created`` (template ``change_card``, occasion ``change_card``), queued by
   ``EnqueueNotifications`` for the client's own people: the recipients that follow the business
   with the role of an owner or staff. The firm's own people (``ca_admin``, ``ca_staff``) hear
   about every client in their daily digest, so the firm's own message is not for them. The
   change card's dedupe key names the rule version, the business, the channel and the recipient,
   so a recipient who has the card already, from the change itself or from an earlier bulk
   notification, gets nothing more: one change, one card per person and business (F9).
3. The unit writes the audit entry ``notification.bulk`` of the tenant: the actor, the change, and
   the counts, with the businesses by outcome; it commits or rolls back with the notifications.

Each business ends in one outcome: ``queued`` when at least one of its people got the card now,
``duplicate`` when every one of them who can be reached had it already, ``no_recipient`` when
nobody can be told (no client recipient follows it, or none has an open address), and
``not_affected``. The use case refuses everything while the flag ``notification.bulk`` is off
(``BulkNotificationsDisabledError``, 503).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from domain_kernel._validation import require_instance
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from notification.application.enqueue import EnqueueNotifications
from notification.domain.errors import BulkNotificationsDisabledError
from notification.domain.occasions import Occasion
from notification.domain.ports import ObligationReader, OpenObligation
from notification.domain.recipients import CA_ROLES, Recipient
from notification.domain.repository import UnitOfWorkFactory
from notification.domain.routing import CREATED_TOPIC, ObligationNotice, route

BULK_ACTION: Final = "notification.bulk"
SUBJECT: Final = "rule_version"
MAX_BUSINESSES: Final = 500
"""The most businesses one request names: a CA firm's whole client list (guide section 1)."""


class BulkKind(StrEnum):
    """What a bulk notification sends."""

    CHANGE_CARD = "change_card"
    """The change card: what changed, from when, what to do and by when."""


class BulkOutcome(StrEnum):
    """What became of one business."""

    QUEUED = "queued"
    DUPLICATE = "duplicate"
    NO_RECIPIENT = "no_recipient"
    NOT_AFFECTED = "not_affected"


def client_recipient(recipient: Recipient) -> bool:
    """Whether the recipient is one of the client's own people, not the CA firm's."""
    return recipient.role not in CA_ROLES


@dataclass(frozen=True, slots=True)
class BulkRequest:
    tenant_id: TenantId
    rule_version_id: RuleVersionId
    business_ids: tuple[BusinessId, ...]
    actor: AuditActor
    kind: BulkKind = BulkKind.CHANGE_CARD
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.rule_version_id, RuleVersionId, "rule_version_id")
        businesses = tuple(self.business_ids)
        for business in businesses:
            require_instance(business, BusinessId, "business_ids")
        if not 1 <= len(businesses) <= MAX_BUSINESSES:
            raise InvariantViolationError(
                f"a bulk notification names 1 to {MAX_BUSINESSES} businesses"
            )
        if len(set(businesses)) != len(businesses):
            raise InvariantViolationError("a bulk notification names a business twice")
        object.__setattr__(self, "business_ids", businesses)
        require_instance(self.actor, AuditActor, "actor")
        require_instance(self.kind, BulkKind, "kind")


@dataclass(frozen=True, slots=True)
class BusinessResult:
    """One business: its outcome, the obligation its card is about (None when not affected),
    and its client recipients by what became of them."""

    business_id: BusinessId
    outcome: BulkOutcome
    obligation_id: ObligationId | None = None
    queued: int = 0
    duplicates: int = 0
    unreachable: int = 0


@dataclass(frozen=True, slots=True)
class BulkResult:
    rule_version_id: RuleVersionId
    kind: BulkKind
    businesses: tuple[BusinessResult, ...] = field(default=())

    def count(self, outcome: BulkOutcome) -> int:
        """How many businesses ended in ``outcome``."""
        return sum(1 for business in self.businesses if business.outcome is outcome)

    @property
    def notifications_queued(self) -> int:
        """Change cards queued, one per client recipient and business."""
        return sum(business.queued for business in self.businesses)

    def counts(self) -> Mapping[str, int]:
        """The businesses by outcome and the cards queued: what the audit entry records."""
        return {
            "businesses": len(self.businesses),
            **{outcome.value: self.count(outcome) for outcome in BulkOutcome},
            "notifications_queued": self.notifications_queued,
        }


class BulkNotify:
    def __init__(
        self,
        unit_of_work: UnitOfWorkFactory,
        enqueue: EnqueueNotifications,
        obligations: ObligationReader,
        *,
        enabled: bool,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._enqueue = enqueue
        self._obligations = obligations
        self._enabled = enabled

    def require_enabled(self) -> None:
        """Raise ``BulkNotificationsDisabledError`` while the flag is off."""
        if not self._enabled:
            raise BulkNotificationsDisabledError()

    def run(self, request: BulkRequest) -> BulkResult:
        """Queue the change cards and audit them; raises ``DependencyUnavailableError`` when
        the obligation service cannot answer, before anything is queued."""
        self.require_enabled()
        cards = {business: self._card(request, business) for business in request.business_ids}
        template = route(CREATED_TOPIC)
        assert template is not None, "obligation.created sends the change card"
        results: list[BusinessResult] = []
        with self._unit_of_work(request.tenant_id) as unit:
            for business, card in cards.items():
                if card is None:
                    results.append(BusinessResult(business, BulkOutcome.NOT_AFFECTED))
                    continue
                notice = ObligationNotice(
                    tenant_id=request.tenant_id,
                    business_id=business,
                    occasion=Occasion.change_card(card.obligation_id, card.rule_version_id),
                    template_key=template.template_key,
                    params=_params(card),
                )
                enqueued = self._enqueue.run_in(unit, notice, audience=client_recipient)
                results.append(
                    BusinessResult(
                        business,
                        _outcome(enqueued.queued, enqueued.duplicates),
                        card.obligation_id,
                        enqueued.queued,
                        enqueued.duplicates,
                        enqueued.unreachable,
                    )
                )
            result = BulkResult(request.rule_version_id, request.kind, tuple(results))
            unit.audit.write(_entry(request, result))
        return result

    def _card(self, request: BulkRequest, business: BusinessId) -> OpenObligation | None:
        """The obligation the business's card is about: its first open one of the version."""
        found: Sequence[OpenObligation] = self._obligations.open_obligations(
            request.tenant_id, business, request.rule_version_id
        )
        return next(iter(found), None)


def _params(card: OpenObligation) -> dict[str, object]:
    """What the card states, as ``obligation.created`` states it (``infrastructure.events_in``)."""
    return {
        "title": card.title,
        "steps": list(card.steps),
        "due_at": None if card.due_at is None else card.due_at.isoformat(),
        "rule_version_id": str(card.rule_version_id),
    }


def _outcome(queued: int, duplicates: int) -> BulkOutcome:
    if queued:
        return BulkOutcome.QUEUED
    if duplicates:
        return BulkOutcome.DUPLICATE
    return BulkOutcome.NO_RECIPIENT


def _entry(request: BulkRequest, result: BulkResult) -> AuditEntry:
    """``notification.bulk`` of the tenant: the change, the actor, and the counts with the
    businesses by outcome. It names businesses and obligations, never a person's address."""
    by_outcome = {
        outcome.value: [
            str(business.business_id)
            for business in result.businesses
            if business.outcome is outcome
        ]
        for outcome in BulkOutcome
    }
    return AuditEntry(
        action=BULK_ACTION,
        tenant_id=request.tenant_id,
        subject_type=SUBJECT,
        subject_id=str(request.rule_version_id),
        actor=request.actor,
        after={"kind": request.kind.value, **result.counts(), "outcomes": by_outcome},
        correlation_id=request.correlation_id,
    )
