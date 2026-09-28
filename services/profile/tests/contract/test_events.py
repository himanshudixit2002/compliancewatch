"""profile.updated serialises to a message the published schema accepts."""

from cw_contracts.events import TOPICS, EventEnvelopeV1
from domain_kernel.ids import BusinessId, TenantId, UserId
from profile_service.domain.events import ChangeSource, ProfileUpdated
from py_common.events import decode, encode, to_message

TENANT = TenantId.new()


def test_profile_updated_matches_its_schema() -> None:
    for changed_by in (UserId.new(), None):
        event = ProfileUpdated(
            tenant_id=TENANT,
            business_id=BusinessId.new(),
            profile_version=4,
            changed_attributes=("turnover_band",),
            ontology_version="0.2.0",
            source=ChangeSource.USER_INPUT,
            changed_by=changed_by,
        )
        message = decode(encode(to_message(event)))
        EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
        spec = TOPICS[message.topic]
        assert message.schema_version == spec.version
        assert spec.tenant_scoped
        spec.model.model_validate(message.payload)
