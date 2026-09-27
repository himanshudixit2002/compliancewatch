from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import (
    BusinessId,
    CandidateId,
    CanonicalEntityId,
    ClauseId,
    CorrelationId,
    DecisionId,
    DocumentId,
    EntityId,
    EventId,
    ObligationId,
    RuleId,
    RuleVersionId,
    SourceId,
    TenantId,
    UserId,
)

ID_TYPES: tuple[type[EntityId], ...] = (
    TenantId,
    UserId,
    BusinessId,
    SourceId,
    DocumentId,
    ClauseId,
    CandidateId,
    RuleId,
    RuleVersionId,
    CanonicalEntityId,
    DecisionId,
    ObligationId,
    EventId,
    CorrelationId,
)


def test_fourteen_distinct_id_kinds() -> None:
    assert len(ID_TYPES) == 14
    assert len(set(ID_TYPES)) == 14


@pytest.mark.parametrize("kind", ID_TYPES)
def test_new_is_unique_and_typed(kind: type[EntityId]) -> None:
    first, second = kind.new(), kind.new()
    assert first != second
    assert type(first) is kind
    assert isinstance(first.value, UUID)
    assert first.value.version == 4


@pytest.mark.parametrize("kind", ID_TYPES)
def test_parse_round_trips_through_str(kind: type[EntityId]) -> None:
    original = kind.new()
    parsed = kind.parse(str(original))
    assert parsed == original
    assert type(parsed) is kind
    assert str(parsed) == str(original.value)


@pytest.mark.parametrize("kind", ID_TYPES)
def test_parse_rejects_garbage_with_the_cause(kind: type[EntityId]) -> None:
    with pytest.raises(InvariantViolationError, match=kind.__name__) as info:
        kind.parse("not-a-uuid")
    assert isinstance(info.value.__cause__, ValueError)


@pytest.mark.parametrize("kind", ID_TYPES)
def test_non_uuid_value_is_rejected(kind: type[EntityId]) -> None:
    with pytest.raises(InvariantViolationError, match="value"):
        kind("11111111-1111-1111-1111-111111111111")  # type: ignore[arg-type]


@pytest.mark.parametrize("kind", ID_TYPES)
def test_ids_are_frozen_and_slotted(kind: type[EntityId]) -> None:
    identifier = kind.new()
    with pytest.raises(FrozenInstanceError):
        identifier.value = uuid4()  # type: ignore[misc]
    slots: Sequence[str] = kind.__slots__
    assert list(slots) == []
    assert issubclass(kind, EntityId)
    assert not hasattr(identifier, "__dict__")


def test_same_uuid_in_different_kinds_is_not_equal() -> None:
    raw = uuid4()
    tenant, user = TenantId(raw), UserId(raw)
    as_object: object = tenant
    assert as_object != user
    assert tenant == TenantId(raw)
    assert hash(tenant) == hash(TenantId(raw))
    table: dict[EntityId, str] = {tenant: "tenant", user: "user"}
    assert len(table) == 2
    assert table[TenantId(raw)] == "tenant"
    assert table[UserId(raw)] == "user"


def test_base_class_also_works_on_its_own() -> None:
    raw = uuid4()
    assert EntityId(raw) != TenantId(raw)
    assert str(EntityId.parse(str(raw))) == str(raw)
