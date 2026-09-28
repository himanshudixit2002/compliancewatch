from collections.abc import Sequence
from dataclasses import FrozenInstanceError
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest

from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import (
    ID_NAMESPACE,
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
    derive_id,
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


def test_id_namespace_is_the_documented_uuid5() -> None:
    assert uuid5(NAMESPACE_URL, "urn:compliancewatch:id") == ID_NAMESPACE


def test_derived_ids_are_stable_typed_and_version_5() -> None:
    first = derive_id(ClauseId, "clause", "doc", "en.p1")
    assert first == derive_id(ClauseId, "clause", "doc", "en.p1")
    assert type(first) is ClauseId
    assert first.value.version == 5
    assert first.value == uuid5(ID_NAMESPACE, '["clause","doc","en.p1"]')


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (("clause", "doc", "en.p1"), ("clause", "doc", "en.p2")),
        (("clause", "doc", "en.p1"), ("citation", "doc", "en.p1")),
        (("clause", "a", "bc"), ("clause", "ab", "c")),
        (("clause", "a,b"), ("clause", "a", "b")),
    ],
)
def test_derived_ids_differ_when_any_word_differs(
    left: tuple[str, ...], right: tuple[str, ...]
) -> None:
    assert derive_id(ClauseId, *left) != derive_id(ClauseId, *right)


def test_derived_ids_keep_non_ascii_text() -> None:
    hindi = derive_id(ClauseId, "clause", "doc", "अधिसूचना")
    assert hindi.value == uuid5(ID_NAMESPACE, '["clause","doc","अधिसूचना"]')


@pytest.mark.parametrize(
    ("namespace", "parts"),
    [("", ("a",)), (" ", ("a",)), ("clause", ("",)), ("clause", ("a", "  ")), ("clause", (1,))],
)
def test_derive_id_rejects_blank_or_non_text_words(
    namespace: str, parts: tuple[object, ...]
) -> None:
    with pytest.raises(InvariantViolationError, match="non-blank text parts"):
        derive_id(ClauseId, namespace, *parts)  # type: ignore[arg-type]


def test_derive_id_rejects_a_non_text_namespace() -> None:
    with pytest.raises(InvariantViolationError, match="namespace must be str"):
        derive_id(ClauseId, 5, "a")  # type: ignore[arg-type]
