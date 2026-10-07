"""A tenant's data requests: a copy of its data (an export) or its erasure (a deletion).

A request is made by the tenant's owner or CA admin (``self_service``) or by the regulatory team's
admin for the tenant (``support``), and must be answered within ``DEADLINE``, 30 days after it was
made (docs/legal/data-map.md and the guide's section 16, until counsel confirms them). It is
``received`` until the first export is assembled, ``in_progress`` while some service has not
answered one, and ``completed`` once every service it needs has: ``services_done`` names those that
have. A request past its deadline and not completed is overdue (``is_overdue``), which the
DataRequestOverdue alert pages on.

An export is assembled when it is downloaded and never stored: identity's own data and each
``ExportSource``'s, one section per service. A source that fails leaves the request in progress
with that service pending, and the bundle says so.

Deletion requests have their kind already; the routes refuse them until the erasure cascade
exists.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Protocol

from domain_kernel._validation import require_aware, require_instance
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import EntityId, TenantId

DEADLINE: Final = timedelta(days=30)
"""How long a tenant waits at most for its request (data map; counsel to confirm)."""
MAX_REASON_CHARS: Final = 500
MAX_ACTOR_CHARS: Final = 160
MAX_SERVICE_CHARS: Final = 64
IDENTITY_SERVICE: Final = "identity"
"""The section identity's own data takes in an export, and its name in ``services_done``."""


@dataclass(frozen=True, slots=True)
class DataRequestId(EntityId):
    """A tenant's data request."""


class DataRequestKind(StrEnum):
    EXPORT = "export"
    DELETION = "deletion"


class DataRequestSource(StrEnum):
    SELF_SERVICE = "self_service"
    """The tenant's owner or CA admin asked."""
    SUPPORT = "support"
    """The regulatory team's admin recorded it for the tenant, as support received it."""


class DataRequestStatus(StrEnum):
    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


@dataclass(frozen=True, slots=True)
class DataRequest:
    id: DataRequestId
    tenant_id: TenantId
    kind: DataRequestKind
    source: DataRequestSource
    requested_by: str
    """Who asked, as an audit actor label (``user:<id>``), or '' when no token named them."""
    reason: str
    requested_at: datetime
    deadline_at: datetime
    status: DataRequestStatus = DataRequestStatus.RECEIVED
    services_done: tuple[str, ...] = ()
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        require_instance(self.id, DataRequestId, "id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_instance(self.kind, DataRequestKind, "kind")
        require_instance(self.source, DataRequestSource, "source")
        require_instance(self.requested_by, str, "requested_by")
        if len(self.requested_by) > MAX_ACTOR_CHARS:
            raise InvariantViolationError(f"requested_by has at most {MAX_ACTOR_CHARS} characters")
        require_instance(self.reason, str, "reason")
        if len(self.reason) > MAX_REASON_CHARS:
            raise InvariantViolationError(f"a reason has at most {MAX_REASON_CHARS} characters")
        if self.source is DataRequestSource.SUPPORT and not self.reason.strip():
            raise InvariantViolationError("a support request says why: give its reason")
        require_aware(self.requested_at, "requested_at")
        require_aware(self.deadline_at, "deadline_at")
        if self.deadline_at <= self.requested_at:
            raise InvariantViolationError("a request's deadline comes after it was made")
        require_instance(self.status, DataRequestStatus, "status")
        require_instance(self.services_done, tuple, "services_done")
        for service in self.services_done:
            if not isinstance(service, str) or not 0 < len(service) <= MAX_SERVICE_CHARS:
                raise InvariantViolationError("services_done holds service names")
        if list(self.services_done) != sorted(set(self.services_done)):
            raise InvariantViolationError("services_done is sorted, each service once")
        completed = self.status is DataRequestStatus.COMPLETED
        if completed != (self.completed_at is not None):
            raise InvariantViolationError("a request has completed_at exactly when completed")
        if self.completed_at is not None:
            require_aware(self.completed_at, "completed_at")

    @classmethod
    def new(
        cls,
        tenant_id: TenantId,
        kind: DataRequestKind,
        source: DataRequestSource,
        *,
        requested_by: str,
        reason: str,
        at: datetime,
    ) -> "DataRequest":
        """A request received ``at``, due ``DEADLINE`` later."""
        return cls(
            id=DataRequestId.new(),
            tenant_id=tenant_id,
            kind=kind,
            source=source,
            requested_by=requested_by,
            reason=reason.strip(),
            requested_at=at,
            deadline_at=at + DEADLINE,
        )

    @property
    def is_completed(self) -> bool:
        return self.status is DataRequestStatus.COMPLETED

    def is_overdue(self, now: datetime) -> bool:
        """Past its deadline and not completed."""
        return not self.is_completed and require_aware(now, "now") > self.deadline_at

    def pending(self, expected: Iterable[str]) -> tuple[str, ...]:
        """The services of ``expected`` that have not answered yet; none once completed."""
        if self.is_completed:
            return ()
        done = set(self.services_done)
        return tuple(sorted(service for service in set(expected) if service not in done))

    def record_answers(
        self, answered: Iterable[str], expected: Iterable[str], at: datetime
    ) -> "DataRequest":
        """The request after an export in which ``answered`` services gave their data: they join
        ``services_done``, and the request completes once that covers ``expected``. A completed
        request stays completed."""
        if self.is_completed:
            return self
        done = tuple(sorted(set(self.services_done) | set(answered)))
        if set(expected) <= set(done):
            return replace(
                self,
                services_done=done,
                status=DataRequestStatus.COMPLETED,
                completed_at=require_aware(at, "at"),
            )
        return replace(self, services_done=done, status=DataRequestStatus.IN_PROGRESS)


class DataRequestRepository(Protocol):
    def add(self, request: DataRequest) -> None: ...

    def save(self, request: DataRequest) -> None:
        """Store the request's changed status, services and completion."""
        ...

    def get(self, request_id: DataRequestId) -> DataRequest | None:
        """The unit of work's tenant's request with this id; None for another tenant's."""
        ...

    def list(self) -> list[DataRequest]:
        """The tenant's requests, newest first."""
        ...


@dataclass(frozen=True, slots=True)
class OpenRequests:
    """Every tenant's requests of one kind that are not completed, and how many of them are past
    their deadline: counts only, which is all ``identity.data_requests_open()`` answers."""

    kind: DataRequestKind
    open: int
    overdue: int


class DataRequestDirectory(Protocol):
    def open_counts(self) -> list[OpenRequests]:
        """One entry per kind, zeros included, across every tenant."""
        ...


def counts_by_kind(found: Iterable[OpenRequests]) -> list[OpenRequests]:
    """``found`` with a zero entry for each kind it lacks, in the order of the kinds."""
    by_kind: Mapping[DataRequestKind, OpenRequests] = {entry.kind: entry for entry in found}
    return [by_kind.get(kind, OpenRequests(kind, 0, 0)) for kind in DataRequestKind]


@dataclass(frozen=True, slots=True)
class SourceSection:
    """What one ``ExportSource`` answered for the tenant: its data as JSON, with when it was
    generated, or why it could not be had."""

    service: str
    data: Mapping[str, object] | None
    error: str = ""

    @property
    def answered(self) -> bool:
        return self.data is not None


class ExportSource(Protocol):
    """One service's data of a tenant, for an export."""

    @property
    def service(self) -> str: ...

    def export(self, tenant_id: TenantId) -> SourceSection:
        """The tenant's data at the service. A failure is a section without data and with the
        reason, never an exception: the export goes on without it."""
        ...


def parse_export_sources(text: str) -> Mapping[str, str]:
    """``service=url,service=url`` as a mapping; blank is none. A pair without ``=``, an empty
    name or URL, a name that is not lower-case letters and hyphens, a URL that is not http(s), or
    a service named twice is a ValueError."""
    sources: dict[str, str] = {}
    for item in text.split(","):
        if not item.strip():
            continue
        name, separator, url = item.strip().partition("=")
        name, url = name.strip(), url.strip().rstrip("/")
        if not separator or not name or not url:
            raise ValueError(f"CW_IDENTITY_EXPORT_SOURCES: {item.strip()!r} is not service=url")
        if not name.replace("-", "").isalpha() or not name.islower() or name.startswith("-"):
            raise ValueError(f"CW_IDENTITY_EXPORT_SOURCES: {name!r} is not a service name")
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"CW_IDENTITY_EXPORT_SOURCES: the URL of {name} is not http(s)")
        if name in sources:
            raise ValueError(f"CW_IDENTITY_EXPORT_SOURCES names {name} twice")
        sources[name] = url
    return sources
