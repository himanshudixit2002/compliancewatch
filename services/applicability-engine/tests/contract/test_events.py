"""applicability.decided serialises to a message its published schema accepts, with exactly the
schema's fields."""

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from applicability_engine.domain.events import ApplicabilityDecided
from applicability_engine.domain.model import Trigger
from cw_contracts.events import TOPICS, EventEnvelopeV1
from domain_kernel.ids import BusinessId, DecisionId, RuleVersionId, TenantId
from domain_kernel.predicates import Applicability
from py_common.events import decode, encode, to_message

SCHEMA = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "events"
    / "schemas"
    / "applicability.decided.v1.json"
)
NOW = datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
TENANT = TenantId.new()


@pytest.mark.parametrize("trigger", list(Trigger))
@pytest.mark.parametrize(
    ("result", "confidence", "needs_review"),
    [(Applicability.APPLIES, 1.0, False), (Applicability.UNSURE, 0.0, True)],
)
def test_applicability_decided_matches_its_schema(
    trigger: Trigger, result: Applicability, confidence: float, needs_review: bool
) -> None:
    event = ApplicabilityDecided(
        tenant_id=TENANT,
        decision_id=DecisionId.new(),
        business_id=BusinessId.new(),
        rule_version_id=RuleVersionId.new(),
        result=result,
        confidence=confidence,
        profile_version=3,
        decided_at=NOW,
        needs_review=needs_review,
        trigger=trigger,
    )
    message = decode(encode(to_message(event)))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert message.schema_version == spec.version
    assert spec.tenant_scoped
    assert message.tenant_id == TENANT.value
    spec.model.model_validate(message.payload)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(message.payload)
    assert set(message.payload) == set(schema["properties"])
