from collections.abc import Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum, IntEnum, StrEnum
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest

from domain_kernel.access import MAX_CLIENT_ID_CHARS, Role
from domain_kernel.audit import (
    ACTION_PATTERN,
    CORRELATION_ID_PATTERN,
    MAX_ACTION_CHARS,
    MAX_ACTOR_ID_CHARS,
    MAX_ACTOR_LABEL_CHARS,
    MAX_REASON_CHARS,
    MAX_SUBJECT_ID_CHARS,
    MAX_SUBJECT_TYPE_CHARS,
    AuditActor,
    AuditActorKind,
    AuditEntry,
    AuditEntryId,
    AuditSink,
)
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId, UserId

USER = UserId(UUID("11111111-1111-4111-8111-111111111111"))
TENANT = TenantId(UUID("22222222-2222-4222-8222-222222222222"))
AT = datetime(2026, 10, 4, 9, 30, tzinfo=UTC)
REVIEWER = AuditActor.user(USER, [Role.REVIEWER])


class Colour(StrEnum):
    GREEN = "green"


class Legacy(str, Enum):  # noqa: UP042 - the mix-in whose str() is not its value
    OPEN = "open"


class Level(IntEnum):
    HIGH = 3


def entry(**overrides: object) -> AuditEntry:
    values: dict[str, object] = {
        "action": "applicability.review.resolve",
        "tenant_id": TENANT,
        "subject_type": "review_item",
        "subject_id": "33333333-3333-4333-8333-333333333333",
        "actor": REVIEWER,
        "reason": "Example premises checked against the clause",
        "before": {"status": "open"},
        "after": {"status": "resolved", "resolution": "applies"},
        "occurred_at": AT,
        "correlation_id": "0f8fad5bd9cb469fa16570867728950e",
    }
    values.update(overrides)
    return AuditEntry(**values)  # type: ignore[arg-type]


def test_a_user_is_labelled_with_the_roles_they_acted_with() -> None:
    actor = AuditActor.user(USER, [Role.REVIEWER, Role.ADMIN, Role.REVIEWER])
    assert (actor.kind, actor.id, actor.label) == (
        AuditActorKind.USER,
        "11111111-1111-4111-8111-111111111111",
        "admin, reviewer",
    )
    assert AuditActor.user(USER).label == "user"
    with pytest.raises(InvariantViolationError, match="roles must be Role"):
        AuditActor.user(USER, ["reviewer"])  # type: ignore[list-item]
    with pytest.raises(InvariantViolationError, match="user_id must be UserId"):
        AuditActor.user(TENANT)  # type: ignore[arg-type]


def test_a_service_and_the_system_carry_their_kind_in_the_label() -> None:
    service = AuditActor.service("pipeline")
    assert (service.kind, service.id, service.label) == (
        AuditActorKind.SERVICE,
        "pipeline",
        "service:pipeline",
    )
    system = AuditActor.system("applicability-engine")
    assert (system.kind, system.id, system.label) == (
        AuditActorKind.SYSTEM,
        "applicability-engine",
        "system:applicability-engine",
    )
    assert [kind.value for kind in AuditActorKind] == ["user", "service", "system"]


@pytest.mark.parametrize(
    ("kind", "actor_id", "label", "message"),
    [
        ("user", "pipeline", "reviewer", "kind must be AuditActorKind"),
        (AuditActorKind.USER, "not-a-uuid", "reviewer", "a user actor's id is a user id"),
        (AuditActorKind.USER, "0F8FAD5B-D9CB-469F-A165-70867728950E", "x", "a user actor's id"),
        (AuditActorKind.SERVICE, "", "service:", "actor id must not be blank"),
        (AuditActorKind.SERVICE, " pipeline", "service:pipeline", "leading or trailing"),
        (AuditActorKind.SERVICE, "p" * (MAX_ACTOR_ID_CHARS + 1), "x", "actor id has at most"),
        (AuditActorKind.SYSTEM, "sweep", "   ", "actor label must not be blank"),
        (AuditActorKind.SYSTEM, "sweep", "l" * (MAX_ACTOR_LABEL_CHARS + 1), "label has at most"),
        (AuditActorKind.SYSTEM, 7, "system:7", "actor id must be str"),
    ],
)
def test_a_malformed_actor_is_refused(
    kind: object, actor_id: object, label: object, message: str
) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        AuditActor(kind, actor_id, label)  # type: ignore[arg-type]


def test_an_actor_id_fits_a_service_client_id() -> None:
    assert MAX_ACTOR_ID_CHARS == MAX_CLIENT_ID_CHARS
    assert AuditActor.service("c" * MAX_CLIENT_ID_CHARS).label.startswith("service:")


def test_an_entry_keeps_what_it_was_given() -> None:
    made = entry()
    assert isinstance(made.entry_id, AuditEntryId)
    assert (made.action, made.tenant_id, made.subject_type) == (
        "applicability.review.resolve",
        TENANT,
        "review_item",
    )
    assert (made.actor, made.occurred_at, made.correlation_id) == (
        REVIEWER,
        AT,
        "0f8fad5bd9cb469fa16570867728950e",
    )
    assert made.before == {"status": "open"}
    assert made.after == {"status": "resolved", "resolution": "applies"}


def test_the_defaults_a_platform_wide_entry_takes() -> None:
    before = utc_now()
    made = AuditEntry(
        action="applicability.fanout.pause",
        tenant_id=None,
        subject_type="fanout_run",
        subject_id="run-1",
        actor=AuditActor.system("applicability-engine"),
    )
    assert made.tenant_id is None
    assert (made.reason, made.before, made.after, made.correlation_id) == ("", None, None, None)
    assert before <= made.occurred_at <= utc_now()
    assert made.entry_id != entry().entry_id


def test_entries_compare_by_value_and_hash_without_their_state() -> None:
    entry_id = AuditEntryId.new()
    first, second = entry(entry_id=entry_id), entry(entry_id=entry_id)
    assert first == second
    assert hash(first) == hash(second)
    assert first != entry(entry_id=entry_id, after={"status": "resolved"})
    with pytest.raises(FrozenInstanceError):
        first.reason = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "action",
    ["applicability.review.resolve", "rule.publish", "a1.b_2", "fanout_run.hold.release"],
)
def test_valid_actions(action: str) -> None:
    assert entry(action=action).action == action
    assert ACTION_PATTERN.fullmatch(action)


@pytest.mark.parametrize(
    "action",
    ["", "resolve", "Applicability.review", "applicability..resolve", "1a.b", "a.b.", "a b.c"],
)
def test_an_action_is_a_dotted_name(action: str) -> None:
    with pytest.raises(InvariantViolationError, match="action must match"):
        entry(action=action)


def test_the_bounded_fields_say_their_limit() -> None:
    long_action = "a." + "b" * (MAX_ACTION_CHARS - 1)
    with pytest.raises(InvariantViolationError, match=f"action has at most {MAX_ACTION_CHARS}"):
        entry(action=long_action)
    with pytest.raises(InvariantViolationError, match="subject_type has at most"):
        entry(subject_type="s" * (MAX_SUBJECT_TYPE_CHARS + 1))
    with pytest.raises(InvariantViolationError, match="subject_id has at most"):
        entry(subject_id="s" * (MAX_SUBJECT_ID_CHARS + 1))
    with pytest.raises(InvariantViolationError, match="reason has at most"):
        entry(reason="r" * (MAX_REASON_CHARS + 1))
    assert len(entry(reason="r" * MAX_REASON_CHARS).reason) == MAX_REASON_CHARS


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("subject_type", "ReviewItem", "subject_type must match"),
        ("subject_type", "review-item", "subject_type must match"),
        ("subject_id", "", "subject_id must not be blank"),
        ("subject_id", " id", "leading or trailing whitespace"),
        ("tenant_id", USER, "tenant_id must be TenantId"),
        ("actor", "user:x", "actor must be AuditActor"),
        ("reason", None, "reason must be str"),
        ("occurred_at", datetime(2026, 10, 4, 9, 30), "timezone-aware"),
        ("occurred_at", date(2026, 10, 4), "must be a datetime"),
        ("entry_id", uuid4(), "entry_id must be AuditEntryId"),
    ],
)
def test_a_malformed_entry_is_refused(field: str, value: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        entry(**{field: value})


def test_a_reason_is_kept_verbatim_and_may_be_empty() -> None:
    assert entry(reason="").reason == ""
    assert entry(reason="  spaced note \n").reason == "  spaced note \n"


@pytest.mark.parametrize(
    "correlation_id",
    [
        "0f8fad5bd9cb469fa16570867728950e",
        "0f8fad5b-d9cb-469f-a165-70867728950e",
        "request-1.retry_2",
        "x" * 64,
    ],
)
def test_correlation_ids_of_the_request_id_shape(correlation_id: str) -> None:
    assert entry(correlation_id=correlation_id).correlation_id == correlation_id
    assert CORRELATION_ID_PATTERN.fullmatch(correlation_id)


@pytest.mark.parametrize("correlation_id", ["", "x" * 65, "has space", "a/b", "é"])
def test_other_correlation_ids_are_refused(correlation_id: str) -> None:
    with pytest.raises(InvariantViolationError, match="correlation_id must be 1 to 64"):
        entry(correlation_id=correlation_id)


def test_a_correlation_id_is_text() -> None:
    with pytest.raises(InvariantViolationError, match="correlation_id must be str"):
        entry(correlation_id=uuid4())


def test_the_state_is_copied_into_read_only_json() -> None:
    ids: list[object] = ["a", ("b", None)]
    nested: dict[str, object] = {
        "status": Colour.GREEN,
        "legacy": Legacy.OPEN,
        "level": Level.HIGH,
        "ids": ids,
        "counts": {"open": 1, "ratio": 0.5, "flag": True},
    }
    made = entry(before=nested, after=None)
    nested["status"] = "changed"
    ids.append("c")
    state = made.before
    assert isinstance(state, MappingProxyType)
    assert dict(state) == {
        "status": "green",
        "legacy": "open",
        "level": 3,
        "ids": ("a", ("b", None)),
        "counts": {"open": 1, "ratio": 0.5, "flag": True},
    }
    assert type(state["status"]) is str
    assert type(state["legacy"]) is str
    assert type(state["level"]) is int
    counts = state["counts"]
    assert isinstance(counts, MappingProxyType)
    with pytest.raises(TypeError):
        counts["open"] = 2  # type: ignore[index]
    assert made.after is None


@pytest.mark.parametrize(
    ("state", "message"),
    [
        (["status", "open"], "before must be a mapping or None, got list"),
        ({1: "open"}, "before keys must be strings"),
        ({"due": date(2026, 10, 4)}, r"before\.due must hold JSON"),
        ({"id": uuid4()}, r"before\.id must hold JSON"),
        ({"amount": Decimal("1.5")}, r"before\.amount must hold JSON"),
        ({"tags": {"a"}}, r"before\.tags must hold JSON"),
        ({"raw": b"x"}, r"before\.raw must hold JSON"),
        ({"items": [{"ok": 1}, {"at": AT}]}, r"before\.items\[1\]\.at must hold JSON"),
        ({"ratio": float("nan")}, r"before\.ratio must be a finite number"),
        ({"ratio": float("inf")}, "finite number"),
    ],
)
def test_state_that_is_not_json_is_refused(state: object, message: str) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        entry(before=state)


def test_an_offset_time_is_kept_as_given() -> None:
    offset = AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert entry(occurred_at=offset).occurred_at == AT


def test_a_sink_is_anything_with_write() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.entries: list[AuditEntry] = []

        def write(self, entry: AuditEntry) -> None:
            self.entries.append(entry)

    def record(sink: AuditSink, made: AuditEntry) -> None:
        sink.write(made)

    recorder = Recorder()
    made = entry()
    record(recorder, made)
    assert recorder.entries == [made]


def test_state_mappings_keep_their_key_order() -> None:
    state: Mapping[str, object] = {"b": 1, "a": 2}
    made = entry(after=state)
    assert made.after is not None
    assert list(made.after) == ["b", "a"]
