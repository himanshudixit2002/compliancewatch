"""The audit trail: who may read which entries, the export, and the entries identity writes.

``ReadAuditTrail`` answers one page of the trail for the caller, in the scope their roles give
(``identity.domain.audit.AuditScope``), after checking the session of a verified token against
the store as the user routes do:

- owners, CA admins and compliance leads read their tenant's entries (``TENANT``);
- analysts, reviewers and admins of the internal tenant read the platform's entries, the rows
  of no tenant, and their own tenant's (``REGULATORY``); the scope checks the tenant's kind as
  well as the roles;
- anyone else is refused (403), and so is a service: the trail answers for people.

In header mode (local runs before tokens) the anonymous caller reads the entries of the tenant
the header names and never the platform's; the route refuses a request without a token in dual
and token mode.

``ExportAuditTrail`` is ``identity-admin audit-export``: every entry from one instant to another,
oldest first, as NDJSON (one ``entry_document`` per line), with ``manifest.json`` beside it
holding the file's SHA-256, the count, the range and when it was generated. It reads in the
``EXPORT`` scope and writes one ``audit.exported`` entry of no tenant naming what it wrote. It
writes into a directory that is missing or empty, and nowhere else:

- both files are first written under ``*.partial`` names, each opened exclusively (``"xb"``), so
  two exports into one directory never overwrite each other;
- the ``audit.exported`` entry commits only after the read has finished and both files are
  written; if the read or that commit fails, the partial files are deleted and nothing is left;
- the files take their final names only after the entry commits. So ``manifest.json`` in a
  directory always has its ``audit.exported`` row. A crash between the commit and the renames
  leaves ``*.partial`` files and a row: export the range again into a new directory.

Rows commit with the ``occurred_at`` their service gave them before the commit, so a range is only
settled some time after it ends: ``settled_until(now)`` is the latest ``--to`` that waits out
``EXPORT_GRACE``, the default of ``--to``.

``audit_entry`` builds the entries identity's own use cases write, each in the unit of work of
the change: ``tenant.created``, ``user.invited``, ``user.roles_changed``, ``user.disabled``,
``consent.recorded``, ``subscription.started``, ``subscription.status_changed``,
``subscription.event_ignored``, ``subscription.unmatched`` and, from the operator's CLI,
``service_client.created`` and ``service_client.revoked``. Their volume is that
of people's actions (sign-ups, invitations, role changes, consents, billing changes): a few rows
per tenant per month.
"""

import hashlib
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from domain_kernel.access import REGULATORY_ROLES, Principal, PrincipalKind, Role
from domain_kernel.audit import AuditActor, AuditEntry
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from identity.application.sessions import check_session
from identity.domain.audit import AuditQuery, AuditReader, AuditScope, entry_document
from identity.domain.repository import UnitOfWorkFactory
from identity.domain.tenancy import TenantKind
from py_common.audit import audit_actor, current_correlation_id
from py_common.auth.errors import AuthForbiddenError

SERVICE: Final = "identity"
CLI_ACTOR: Final = AuditActor.system("identity-admin")
"""The actor of what an operator does with ``identity-admin``."""
BILLING_WEBHOOK_ACTOR: Final = AuditActor.system("billing-webhook")
"""The actor of a subscription change the billing provider reported."""
TENANT_READERS: Final = frozenset({Role.OWNER, Role.CA_ADMIN, Role.COMPLIANCE_LEAD})
"""Roles that read their tenant's trail."""
EXPORT_ACTION: Final = "audit.exported"
NDJSON_NAME: Final = "audit-events.ndjson"
MANIFEST_NAME: Final = "manifest.json"
PARTIAL_SUFFIX: Final = ".partial"
"""What a file of an export is called until its ``audit.exported`` entry commits."""
EXPORT_GRACE: Final = timedelta(days=2)
"""How long after a range ends its rows are taken as committed: a row commits with an
``occurred_at`` its service took before the commit, and a retried event may commit later still."""


def settled_until(now: datetime) -> datetime:
    """The latest export ``--to`` that waits out ``EXPORT_GRACE``: midnight UTC of the day
    ``EXPORT_GRACE`` before ``now``. On the 3rd of a month it is the 1st, so the month before is
    settled."""
    day = (now - EXPORT_GRACE).astimezone(UTC).date()
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def audit_entry(
    action: str,
    *,
    tenant_id: TenantId | None,
    subject_type: str,
    subject_id: str,
    at: datetime,
    before: Mapping[str, object] | None = None,
    after: Mapping[str, object] | None = None,
    reason: str = "",
    actor: AuditActor | None = None,
    principal: Principal | None = None,
) -> AuditEntry:
    """An entry identity writes: by ``actor``, else ``principal``'s user or service, else the
    request's bound principal, else ``system:identity``; with the request's correlation id."""
    return AuditEntry(
        action=action,
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        actor=actor or audit_actor(SERVICE, principal),
        reason=reason,
        before=before,
        after=after,
        occurred_at=at,
        correlation_id=current_correlation_id(),
    )


def sorted_role_names(roles: frozenset[Role]) -> list[str]:
    return sorted(role.value for role in roles)


@dataclass(frozen=True, slots=True)
class AuditTrailPage:
    """Up to ``limit + 1`` entries, newest first, and the scope they were read in."""

    scope: AuditScope
    entries: list[AuditEntry]


class ReadAuditTrail:
    def __init__(self, reader: AuditReader, unit_of_work: UnitOfWorkFactory) -> None:
        self._reader = reader
        self._unit_of_work = unit_of_work

    def scope_for(self, actor: Principal, tenant_id: TenantId) -> AuditScope:
        """The scope ``actor`` reads in; ``AuthForbiddenError`` for a role that reads none."""
        if actor.kind is PrincipalKind.SERVICE:
            raise AuthForbiddenError("the audit trail answers for a person, not a service")
        if not actor.is_authenticated:
            return AuditScope.TENANT
        with self._unit_of_work(tenant_id) as uow:
            # A tenant being deleted still reads its own trail: the erasures are on it.
            tenant, user = check_session(uow, actor, deleting_ok=True)
        if user.roles & REGULATORY_ROLES and tenant.kind is TenantKind.INTERNAL:
            # The tenancy rules keep these roles to the internal tenant already; a customer
            # tenant never reads the platform's rows even if one rule slips.
            return AuditScope.REGULATORY
        if user.roles & TENANT_READERS:
            return AuditScope.TENANT
        raise AuthForbiddenError(
            "the audit trail needs one of: admin, analyst, ca_admin, compliance_lead, owner, "
            "reviewer"
        )

    def run(self, actor: Principal, tenant_id: TenantId, query: AuditQuery) -> AuditTrailPage:
        scope = self.scope_for(actor, tenant_id)
        return AuditTrailPage(scope, self._reader.page(scope, tenant_id, query))


@dataclass(frozen=True, slots=True)
class ExportManifest:
    file: str
    sha256: str
    count: int
    since: datetime
    until: datetime
    generated_at: datetime

    def document(self) -> dict[str, object]:
        return {
            "file": self.file,
            "format": "ndjson",
            "sha256": self.sha256,
            "count": self.count,
            "range": {"from": self.since.isoformat(), "to": self.until.isoformat()},
            "generated_at": self.generated_at.isoformat(),
        }


class ExportAuditTrail:
    def __init__(
        self,
        reader: AuditReader,
        unit_of_work: UnitOfWorkFactory,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._reader = reader
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(self, since: datetime, until: datetime, out: Path) -> ExportManifest:
        """Write the entries from ``since`` to ``until`` into ``out`` (made when missing; a
        directory that holds any file is refused) and answer the manifest."""
        AuditQuery(since=since, until=until)  # the same checks as the route's range
        out.mkdir(parents=True, exist_ok=True)
        if any(out.iterdir()):
            raise InvariantViolationError(f"{out} is not empty; name a new directory")
        target, manifest_path = out / NDJSON_NAME, out / MANIFEST_NAME
        partial_target = target.with_name(NDJSON_NAME + PARTIAL_SUFFIX)
        partial_manifest = manifest_path.with_name(MANIFEST_NAME + PARTIAL_SUFFIX)
        created: list[Path] = []
        try:
            manifest = self._write(since, until, partial_target, partial_manifest, created)
            with self._unit_of_work(None) as uow:
                uow.audit.write(
                    audit_entry(
                        EXPORT_ACTION,
                        tenant_id=None,
                        subject_type="audit_export",
                        subject_id=f"{since.isoformat()}/{until.isoformat()}",
                        at=manifest.generated_at,
                        after={"count": manifest.count, "sha256": manifest.sha256},
                        actor=CLI_ACTOR,
                    )
                )
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
        os.rename(partial_target, target)
        os.rename(partial_manifest, manifest_path)
        return manifest

    def _write(
        self,
        since: datetime,
        until: datetime,
        target: Path,
        manifest_path: Path,
        created: list[Path],
    ) -> ExportManifest:
        """Write the NDJSON and the manifest to ``target`` and ``manifest_path``, each opened
        exclusively; ``created`` gathers the files this call made, for the caller to delete."""
        digest = hashlib.sha256()
        count = 0
        with target.open("xb") as handle:
            created.append(target)
            for entry in self._reader.export(since, until):
                line = (
                    json.dumps(entry_document(entry), ensure_ascii=False, sort_keys=True) + "\n"
                ).encode("utf-8")
                handle.write(line)
                digest.update(line)
                count += 1
        manifest = ExportManifest(
            NDJSON_NAME, digest.hexdigest(), count, since, until, self._clock()
        )
        with manifest_path.open("x", encoding="utf-8") as handle:
            created.append(manifest_path)
            handle.write(json.dumps(manifest.document(), indent=2, sort_keys=True) + "\n")
        return manifest
