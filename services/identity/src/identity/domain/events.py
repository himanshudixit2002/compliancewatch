"""Events the identity service publishes through its outbox; payload fields follow
packages/contracts/events (tenant.created, user.role.changed and tenant.deletion.requested;
identity's tenant.data.erased is the kernel's ``domain_kernel.erasure.TenantDataErased``)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from domain_kernel._validation import require_aware, require_instance, require_int
from domain_kernel.access import Role
from domain_kernel.erasure import DELETION_REQUESTED_TOPIC
from domain_kernel.errors import InvariantViolationError
from domain_kernel.events import DomainEvent
from domain_kernel.ids import UserId
from identity.domain.tenancy import REGIONS, TenantKind


class RoleChangeReason(StrEnum):
    CREATED = "created"
    """The first user of a new tenant."""
    INVITED = "invited"
    ROLES_CHANGED = "roles_changed"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantCreated(DomainEvent):
    topic: ClassVar[str] = "tenant.created"
    schema_version: ClassVar[str] = "1.0.0"

    kind: TenantKind
    region: str
    created_by: UserId
    created_at: datetime

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is None:
            raise InvariantViolationError("tenant.created names the tenant it created")
        require_instance(self.kind, TenantKind, "kind")
        if self.region not in REGIONS:
            raise InvariantViolationError(f"region must be one of {', '.join(REGIONS)}")
        require_instance(self.created_by, UserId, "created_by")
        require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True, kw_only=True)
class UserRoleChanged(DomainEvent):
    """``roles`` are the roles the user holds after the change, empty for a disabled user."""

    topic: ClassVar[str] = "user.role.changed"
    schema_version: ClassVar[str] = "1.0.0"

    user_id: UserId
    roles: tuple[Role, ...]
    previous_roles: tuple[Role, ...]
    reason: RoleChangeReason
    session_version: int
    changed_by: UserId | None = None

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is None:
            raise InvariantViolationError("user.role.changed names the user's tenant")
        require_instance(self.user_id, UserId, "user_id")
        for name, roles in (("roles", self.roles), ("previous_roles", self.previous_roles)):
            require_instance(roles, tuple, name)
            if not all(isinstance(role, Role) for role in roles) or len(set(roles)) != len(roles):
                raise InvariantViolationError(f"{name} must hold distinct Role members")
        require_instance(self.reason, RoleChangeReason, "reason")
        require_int(self.session_version, "session_version", minimum=0)
        if self.changed_by is not None:
            require_instance(self.changed_by, UserId, "changed_by")


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantDeletionRequested(DomainEvent):
    """The tenant asked for its data to be deleted; every service that holds some erases it.
    ``requested_by`` is the user who asked, None for a support request. Audit rows are kept
    (``retain_audit``, always true): they are masked and kept seven years."""

    topic: ClassVar[str] = DELETION_REQUESTED_TOPIC
    schema_version: ClassVar[str] = "1.0.1"

    requested_by: UserId | None
    requested_at: datetime
    deadline_at: datetime
    retain_audit: bool = True
    reason: str = ""

    def __post_init__(self) -> None:
        DomainEvent.__post_init__(self)
        if self.tenant_id is None:
            raise InvariantViolationError("tenant.deletion.requested names the tenant")
        if self.requested_by is not None:
            require_instance(self.requested_by, UserId, "requested_by")
        require_aware(self.requested_at, "requested_at")
        require_aware(self.deadline_at, "deadline_at")
        if self.deadline_at <= self.requested_at:
            raise InvariantViolationError("the deadline comes after the request")
        if self.retain_audit is not True:
            raise InvariantViolationError("audit records are always kept (retain_audit)")
        require_instance(self.reason, str, "reason")


def sorted_roles(roles: frozenset[Role]) -> tuple[Role, ...]:
    """Roles in the order events carry them: by value."""
    return tuple(sorted(roles, key=lambda role: role.value))
