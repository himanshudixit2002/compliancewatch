"""The audit trail: who acted, what they did to what, why, and the state before and after.

Guide sections 9, 15 and 16: an immutable audit log, kept seven years, records the actor and the
reason of every admin action and of every change an internal tool makes to customer data. An
``AuditEntry`` is one row of it. A use case writes the entry through the ``AuditSink`` of the
unit of work that holds the action, so the entry commits or rolls back with the action;
``py_common.audit`` has the table, the Postgres writer and the memory twin.

- ``AuditActor``: who acted. A signed-in person (``user``: the user id, labelled with the roles
  they acted with), a service client (``service``: the client id), or the system itself
  (``system``: the service or job that acted for nobody). A label never names a person: a name
  is personal data, so a reader of the trail resolves the user id instead.
- ``AuditEntry``: the action as a dotted name (``applicability.review.resolve``), the tenant
  whose data it touched or None for a platform-wide action, the subject (a type and an id), the
  actor, the reason, the state before and after as JSON, when it happened, and the correlation
  id of the request or event behind it. The JSON is copied into read-only mappings and tuples.
- ``AuditSink``: where a unit of work writes its entries.
"""

import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol, Self
from uuid import UUID

from domain_kernel._validation import require_aware, require_instance, require_text
from domain_kernel.access import MAX_CLIENT_ID_CHARS, Role
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import EntityId, TenantId, UserId

ACTION_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+")
"""An action is a dotted name, ``<domain>.<object>.<verb>``: ``applicability.review.resolve``."""
SUBJECT_TYPE_PATTERN: Final = re.compile(r"[a-z][a-z0-9_]*")
"""A subject type is a snake_case noun: ``review_item``, ``rule_version``."""
CORRELATION_ID_PATTERN: Final = re.compile(r"[A-Za-z0-9._-]{1,64}")
"""What a correlation id may look like: the request id shape ``py_common.request_context``
reuses or mints (32 hex digits), which an event's correlation id in its UUID form also fits."""

MAX_ACTION_CHARS: Final = 120
MAX_SUBJECT_TYPE_CHARS: Final = 64
MAX_SUBJECT_ID_CHARS: Final = 200
MAX_ACTOR_ID_CHARS: Final = MAX_CLIENT_ID_CHARS
"""A user id, a service client id or the name of a service or job."""
MAX_ACTOR_LABEL_CHARS: Final = 200
MAX_REASON_CHARS: Final = 2_000


class AuditActorKind(StrEnum):
    """Who acted: a signed-in person, a service client, or the system itself."""

    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class AuditActor:
    """Who acted, as the audit row records it.

    - ``user``: ``id`` is the user id; ``label`` the roles the person acted with, sorted and
      joined (``admin, reviewer``), or ``user`` when they held none.
    - ``service``: ``id`` is the service client id; ``label`` is ``service:<client>``.
    - ``system``: ``id`` names the service or job that acted for nobody, such as a consumer or a
      sweep; ``label`` is ``system:<name>``.

    Build actors with ``user``, ``service`` and ``system``; any other label is the caller's.
    """

    kind: AuditActorKind
    id: str
    label: str

    def __post_init__(self) -> None:
        require_instance(self.kind, AuditActorKind, "kind")
        _require_bounded(require_text(self.id, "actor id"), MAX_ACTOR_ID_CHARS, "actor id")
        if self.kind is AuditActorKind.USER:
            _require_user_id(self.id)
        _require_bounded(
            require_text(self.label, "actor label"), MAX_ACTOR_LABEL_CHARS, "actor label"
        )

    @classmethod
    def user(cls, user_id: UserId, roles: Iterable[Role] = ()) -> Self:
        """A person, labelled with the roles they acted with."""
        require_instance(user_id, UserId, "user_id")
        names = sorted({require_instance(role, Role, "roles").value for role in roles})
        return cls(AuditActorKind.USER, str(user_id), ", ".join(names) or "user")

    @classmethod
    def service(cls, client_id: str) -> Self:
        """A service client, by the client id its token names, whether or not it acted for a
        tenant."""
        return cls(AuditActorKind.SERVICE, client_id, f"service:{client_id}")

    @classmethod
    def system(cls, name: str) -> Self:
        """The system itself, named for the service or job that acted for nobody."""
        return cls(AuditActorKind.SYSTEM, name, f"system:{name}")


@dataclass(frozen=True, slots=True)
class AuditEntryId(EntityId):
    """One entry of the audit log."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AuditEntry:
    """One audited action.

    ``tenant_id`` is the tenant whose data the action touched, which is not always the actor's:
    a reviewer of the internal tenant who settles another tenant's review item writes an entry
    of that tenant. It is None for a platform-wide action, such as pausing a fan-out over every
    tenant. ``before`` and ``after`` hold the state the action changed, as JSON mappings: None
    when there was nothing before (a creation) or is nothing after (a deletion), or both None
    when the action changes no state (an export). ``reason`` is empty when the action asks for
    none, and kept verbatim otherwise. ``correlation_id`` ties the entry to the request or event
    that caused it.
    """

    entry_id: AuditEntryId = field(default_factory=AuditEntryId.new)
    action: str
    tenant_id: TenantId | None
    subject_type: str
    subject_id: str
    actor: AuditActor
    reason: str = ""
    before: Mapping[str, object] | None = field(default=None, hash=False)
    after: Mapping[str, object] | None = field(default=None, hash=False)
    occurred_at: datetime = field(default_factory=utc_now)
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        require_instance(self.entry_id, AuditEntryId, "entry_id")
        _require_name(self.action, ACTION_PATTERN, MAX_ACTION_CHARS, "action")
        if self.tenant_id is not None:
            require_instance(self.tenant_id, TenantId, "tenant_id")
        _require_name(
            self.subject_type, SUBJECT_TYPE_PATTERN, MAX_SUBJECT_TYPE_CHARS, "subject_type"
        )
        _require_bounded(
            require_text(self.subject_id, "subject_id"), MAX_SUBJECT_ID_CHARS, "subject_id"
        )
        require_instance(self.actor, AuditActor, "actor")
        _require_bounded(require_instance(self.reason, str, "reason"), MAX_REASON_CHARS, "reason")
        object.__setattr__(self, "before", _frozen_state(self.before, "before"))
        object.__setattr__(self, "after", _frozen_state(self.after, "after"))
        require_aware(self.occurred_at, "occurred_at")
        if self.correlation_id is not None:
            correlation = require_instance(self.correlation_id, str, "correlation_id")
            if not CORRELATION_ID_PATTERN.fullmatch(correlation):
                raise InvariantViolationError(
                    "correlation_id must be 1 to 64 of A-Z, a-z, 0-9, '.', '_' and '-', got "
                    f"{correlation!r}"
                )


class AuditSink(Protocol):
    """Where a unit of work writes audit entries: in its own transaction, so an entry commits or
    rolls back with the action it records."""

    def write(self, entry: AuditEntry) -> None: ...


def _require_bounded(text: str, limit: int, name: str) -> str:
    if len(text) > limit:
        raise InvariantViolationError(f"{name} has at most {limit} characters, got {len(text)}")
    return text


def _require_name(value: object, pattern: re.Pattern[str], limit: int, name: str) -> str:
    text = _require_bounded(require_instance(value, str, name), limit, name)
    if not pattern.fullmatch(text):
        raise InvariantViolationError(f"{name} must match {pattern.pattern}, got {text!r}")
    return text


def _require_user_id(text: str) -> None:
    """A user actor's id is the user id in its canonical text form."""
    try:
        value = UUID(text)
    except ValueError:
        value = None
    if value is None or str(value) != text:
        raise InvariantViolationError(f"a user actor's id is a user id, got {text!r}")


def _frozen_state(value: object, name: str) -> Mapping[str, object] | None:
    """A read-only copy of a state mapping, or None."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise InvariantViolationError(
            f"{name} must be a mapping or None, got {value.__class__.__name__}"
        )
    return _frozen_mapping(value, name)


def _frozen_mapping(value: Mapping[object, object], path: str) -> Mapping[str, object]:
    items: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise InvariantViolationError(f"{path} keys must be strings, got {key!r}")
        items[str.__str__(key)] = _frozen_json(item, f"{path}.{key}")
    return MappingProxyType(items)


def _frozen_json(value: object, path: str) -> object:
    """A read-only copy of a JSON value: mappings with text keys become read-only mappings,
    lists and tuples become tuples, and text, numbers, booleans and None stay (an enum member
    becomes its plain value). A number must be finite; anything else (a date, a UUID, a set,
    bytes) is refused, so the caller states the JSON form it means."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvariantViolationError(f"{path} must be a finite number, got {value!r}")
        return float(value)
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, Mapping):
        return _frozen_mapping(value, path)
    if isinstance(value, list | tuple):
        return tuple(_frozen_json(item, f"{path}[{index}]") for index, item in enumerate(value))
    raise InvariantViolationError(
        f"{path} must hold JSON: null, a boolean, a number, text, a list or a mapping; got "
        f"{value.__class__.__name__}"
    )
