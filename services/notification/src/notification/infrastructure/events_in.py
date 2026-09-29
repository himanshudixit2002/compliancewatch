"""Obligation events from the bus as the notices the service acts on.

``notice_from(message)`` reads one event of the topics the service consumes
(``routing.TOPICS``): it validates the payload against the topic's published contract
(``cw_contracts``), looks up its route (``routing.route``), and returns the notice with the
occasion that keys it and the facts the message will state. It returns None for a topic the
service does not consume and for an event that sends nothing: a manual reschedule, a closure the
user made or a reason the routing table does not name. A payload the contract refuses, or an
event without its tenant, raises; the consumer retries it and then dead-letters it.
"""

from uuid import UUID

from pydantic import BaseModel

from cw_contracts.events.obligation_closed_v1 import ObligationClosedV1
from cw_contracts.events.obligation_created_v1 import ObligationCreatedV1
from cw_contracts.events.obligation_due_soon_v1 import ObligationDueSoonV1
from cw_contracts.events.obligation_rescheduled_v1 import ObligationRescheduledV1
from domain_kernel.ids import BusinessId, ObligationId, RuleVersionId, TenantId
from notification.domain.occasions import Occasion
from notification.domain.routing import (
    CLOSED_TOPIC,
    CREATED_TOPIC,
    DUE_SOON_TOPIC,
    RESCHEDULED_TOPIC,
    ObligationNotice,
    Route,
    route,
)
from py_common.events import EventMessage

MODELS: dict[str, type[BaseModel]] = {
    CREATED_TOPIC: ObligationCreatedV1,
    DUE_SOON_TOPIC: ObligationDueSoonV1,
    RESCHEDULED_TOPIC: ObligationRescheduledV1,
    CLOSED_TOPIC: ObligationClosedV1,
}


class MissingTenantError(ValueError):
    """An obligation event without the tenant it belongs to."""


def notice_from(message: EventMessage) -> ObligationNotice | None:
    model = MODELS.get(message.topic)
    if model is None:
        return None
    if message.tenant_id is None:
        raise MissingTenantError(f"{message.topic} event {message.event_id} carries no tenant")
    payload = model.model_validate(message.payload)
    tenant = TenantId(message.tenant_id)
    match payload:
        case ObligationCreatedV1():
            return _notice(
                tenant,
                payload.business_id,
                route(CREATED_TOPIC),
                Occasion.change_card(
                    ObligationId(payload.obligation_id), RuleVersionId(payload.rule_version_id)
                ),
                {
                    "title": payload.title,
                    "steps": [step.root for step in payload.steps],
                    "due_at": None if payload.due_at is None else payload.due_at.isoformat(),
                    "rule_version_id": str(payload.rule_version_id),
                },
            )
        case ObligationDueSoonV1():
            return _notice(
                tenant,
                payload.business_id,
                route(DUE_SOON_TOPIC),
                Occasion.reminder(ObligationId(payload.obligation_id), payload.reminder_index),
                {
                    "title": payload.title,
                    "due_at": payload.due_at.isoformat(),
                    "days_left": payload.days_left,
                    "reminder_index": payload.reminder_index,
                    "rule_version_id": str(payload.rule_version_id),
                },
            )
        case ObligationRescheduledV1():
            cause = payload.caused_by_rule_version_id
            return _notice(
                tenant,
                payload.business_id,
                route(RESCHEDULED_TOPIC, payload.reason.value),
                Occasion.reschedule(ObligationId(payload.obligation_id), payload.new_due_at),
                {
                    "previous_due_at": payload.previous_due_at.isoformat(),
                    "new_due_at": payload.new_due_at.isoformat(),
                    "reschedule_reason": payload.reason.value,
                    "rule_version_id": str(payload.rule_version_id),
                    "source_rule_version_id": None if cause is None else str(cause),
                },
            )
        case ObligationClosedV1():
            return _notice(
                tenant,
                payload.business_id,
                route(CLOSED_TOPIC, payload.reason.value),
                Occasion.closure(ObligationId(payload.obligation_id)),
                {
                    "closed_at": payload.closed_at.isoformat(),
                    "close_reason": payload.reason.value,
                    "rule_version_id": str(payload.rule_version_id),
                },
            )
    return None


def _notice(
    tenant: TenantId,
    business_id: UUID,
    found: Route | None,
    occasion: Occasion,
    params: dict[str, object],
) -> ObligationNotice | None:
    if found is None:
        return None
    if found.occasion is not occasion.kind:
        raise ValueError(f"the route sends a {found.occasion.value}, not a {occasion.kind.value}")
    return ObligationNotice(
        tenant_id=tenant,
        business_id=BusinessId(business_id),
        occasion=occasion,
        template_key=found.template_key,
        params=params,
    )
