"""The events identity publishes serialise to messages the published event schemas accept."""

from datetime import UTC, datetime

import pytest

from cw_contracts.events import TOPICS, EventEnvelopeV1
from domain_kernel.access import Role
from domain_kernel.events import DomainEvent
from domain_kernel.ids import TenantId, UserId
from identity.domain.events import RoleChangeReason, TenantCreated, UserRoleChanged
from identity.domain.tenancy import TenantKind
from py_common.events import decode, encode, to_message

TENANT = TenantId.new()
USER = UserId.new()
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

EVENTS: list[DomainEvent] = [
    TenantCreated(
        tenant_id=TENANT, kind=TenantKind.CA_FIRM, region="in", created_by=USER, created_at=NOW
    ),
    UserRoleChanged(
        tenant_id=TENANT,
        user_id=USER,
        roles=(Role.CA_ADMIN,),
        previous_roles=(),
        reason=RoleChangeReason.CREATED,
        session_version=0,
        changed_by=USER,
    ),
    UserRoleChanged(
        tenant_id=TENANT,
        user_id=UserId.new(),
        roles=(),
        previous_roles=(Role.CA_STAFF, Role.COMPLIANCE_LEAD),
        reason=RoleChangeReason.DISABLED,
        session_version=4,
    ),
]


@pytest.mark.parametrize("event", EVENTS, ids=lambda event: f"{event.topic}")
def test_every_identity_event_matches_its_schema(event: DomainEvent) -> None:
    message = decode(encode(to_message(event)))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert message.schema_version == spec.version
    assert spec.tenant_scoped
    assert message.tenant_id == TENANT.value
    spec.model.model_validate(message.payload)


def test_every_reason_is_in_the_schema() -> None:
    schema_reasons = TOPICS["user.role.changed"].model.model_json_schema()["$defs"]["Reason"]
    assert set(schema_reasons["enum"]) == {reason.value for reason in RoleChangeReason}
