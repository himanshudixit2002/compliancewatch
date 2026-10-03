"""The service's events serialise to messages the published event schemas accept."""

from datetime import timedelta

from cw_contracts.events import TOPICS, EventEnvelopeV1
from eval_service.domain.events import EvalRunCompleted
from eval_service.domain.model import EvalRun, Profile, Suite
from eval_service.testing import NOW, gate
from py_common.events import decode, encode, to_message


def check(event: EvalRunCompleted) -> None:
    message = decode(encode(to_message(event)))
    EventEnvelopeV1.model_validate(message.model_dump(mode="json"))
    spec = TOPICS[message.topic]
    assert message.schema_version == spec.version
    assert not spec.tenant_scoped
    assert message.tenant_id is None
    spec.model.model_validate(message.payload)


def run(previous: EvalRun | None, value: float) -> EvalRun:
    return EvalRun.record(
        suite=Suite.EXTRACTION,
        profile=Profile.NIGHTLY,
        started_at=NOW,
        completed_at=NOW + timedelta(minutes=12),
        measurements=[gate("extraction.extraction_acceptance[gateway]", value, 0.9)],
        previous=previous,
    )


def test_eval_run_completed_matches_its_schema() -> None:
    first = run(None, 0.95)
    check(EvalRunCompleted.of(first))
    check(EvalRunCompleted.of(run(first, 0.8)))
