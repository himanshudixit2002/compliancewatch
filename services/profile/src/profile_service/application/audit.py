"""The audit entries the profile writes (ADR-015: every change to customer data writes an
``audit.event`` row), each through the ``audit`` of the unit of work that makes the change, so
the row commits or rolls back with it.

- ``profile_node.registered``: a use case created a node (entity, registration or location).
  ``before`` is None; ``after`` is ``{"level": ..., "parent_id": ... or None}``. The PAN, the
  GSTIN and the name stay out: the node id resolves them, and they are personal data the log
  would only keep masked. A node that already existed writes nothing.
- ``profile_node.attributes_changed``: a save changed attribute values. ``before`` and ``after``
  hold only the attributes that changed, keyed ``<attribute>`` or, for a per-year value,
  ``<attribute>@<financial year>``, each as ``{"state", "value", "source"}``; a value newly set
  is None before, a value removed is None after. A save that changes nothing writes nothing.
- ``profile_node.prefilled``: the GSTIN and its lookup filled attribute values, in the same
  shape: ``after`` the values it filled, ``before`` what those attributes held. Nothing filled,
  nothing written.

The actor is the request's principal (``audit_actor``), the system as ``system:profile`` when
there is none; ``occurred_at`` is the use case's clock time.

Volume: ``registered`` is one row per node created; ``attributes_changed`` and ``prefilled`` are
one row per node per save that changes something, bounded by the edits a person makes and the
registrations they add.
"""

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from domain_kernel.audit import AuditEntry
from domain_kernel.ids import TenantId
from profile_service.domain.model import AttributeKey, AttributeRecord, ProfileNode
from profile_service.domain.repository import UnitOfWork
from py_common.audit import audit_actor, current_correlation_id

SERVICE: Final = "profile"
"""The service the system actor names: ``SERVICE_NAME`` of ``profile_service.main``."""
SUBJECT: Final = "profile_node"
REGISTERED: Final = "profile_node.registered"
ATTRIBUTES_CHANGED: Final = "profile_node.attributes_changed"
PREFILLED: Final = "profile_node.prefilled"


def record_registered(uow: UnitOfWork, node: ProfileNode, now: datetime) -> None:
    """Write the ``registered`` entry of ``node``, just created in ``uow``."""
    after: dict[str, object] = {
        "level": node.level.value,
        "parent_id": None if node.parent_id is None else str(node.parent_id),
    }
    uow.audit.write(_entry(REGISTERED, node.tenant_id, node, None, after, now))


def record_attributes(
    uow: UnitOfWork,
    action: str,
    before: ProfileNode,
    after: ProfileNode,
    now: datetime,
    *,
    reason: str = "",
) -> None:
    """Write ``action`` for the attribute values that differ between ``before`` and ``after``,
    the same node before and after a save in ``uow``; nothing when none differ."""
    old, new = attribute_diff(before.attributes, after.attributes)
    if not old and not new:
        return
    uow.audit.write(_entry(action, after.tenant_id, after, old, new, now, reason=reason))


def attribute_diff(
    before: Mapping[AttributeKey, AttributeRecord], after: Mapping[AttributeKey, AttributeRecord]
) -> tuple[dict[str, object], dict[str, object]]:
    """The values that changed, before and after, keyed by ``audit_key``."""
    old: dict[str, object] = {}
    new: dict[str, object] = {}
    for storage_key in sorted({*before, *after}, key=lambda key: (key[0], key[1] or "")):
        previous = None if (record := before.get(storage_key)) is None else _record(record)
        current = None if (record := after.get(storage_key)) is None else _record(record)
        if previous != current:
            old[audit_key(storage_key)] = previous
            new[audit_key(storage_key)] = current
    return old, new


def audit_key(storage_key: AttributeKey) -> str:
    """``<attribute>``, or ``<attribute>@<financial year>`` for a per-year value."""
    key, fy_label = storage_key
    return key if fy_label is None else f"{key}@{fy_label}"


def _record(record: AttributeRecord) -> dict[str, object]:
    return {
        "state": record.state.value,
        "value": _json(record.value),
        "source": record.source.value,
    }


def _json(value: object) -> object:
    """A stored value as plain JSON: a date as ISO text, a decimal as text, a set as a sorted
    list."""
    if isinstance(value, frozenset | set):
        return sorted(str(item) for item in value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _entry(
    action: str,
    tenant_id: TenantId,
    node: ProfileNode,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    now: datetime,
    *,
    reason: str = "",
) -> AuditEntry:
    return AuditEntry(
        action=action,
        tenant_id=tenant_id,
        subject_type=SUBJECT,
        subject_id=str(node.id),
        actor=audit_actor(SERVICE),
        reason=reason,
        before=before,
        after=after,
        occurred_at=now,
        correlation_id=current_correlation_id(),
    )
