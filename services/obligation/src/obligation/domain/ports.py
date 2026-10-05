"""What the application layer needs from other services, as protocols the infrastructure
implements."""

from dataclasses import dataclass
from typing import Protocol

from domain_kernel._validation import require_bool, require_instance
from domain_kernel.ids import BusinessId, RuleVersionId, TenantId, UserId
from obligation.domain.rule_versions import RuleVersionRead


class RuleVersionReader(Protocol):
    """Rule versions from the rulebook, in any status."""

    def read(
        self, rule_version_id: RuleVersionId, *, fresh: bool = False
    ) -> RuleVersionRead | None:
        """The version and the facts the cache keeps, or None when the rulebook has no such
        version. A reader may answer from a read it made a short while ago; ``fresh`` asks the
        rulebook again, as a rule event does, since the version's status has just moved. Raises
        ``RulebookUnavailableError`` when the rulebook cannot answer now."""
        ...


@dataclass(frozen=True, slots=True)
class Membership:
    """A user of a tenant as the identity service knows them: whether they may still sign in."""

    user_id: UserId
    tenant_id: TenantId
    active: bool

    def __post_init__(self) -> None:
        require_instance(self.user_id, UserId, "user_id")
        require_instance(self.tenant_id, TenantId, "tenant_id")
        require_bool(self.active, "active")


class TenantMembers(Protocol):
    """The users of each tenant, at the identity service."""

    def membership(self, tenant_id: TenantId, user_id: UserId) -> Membership | None:
        """The user's membership of the tenant, or None when the tenant has no such user.
        Raises ``IdentityUnavailableError`` when the identity service cannot answer now."""
        ...


class ProfileNodes(Protocol):
    """The profile nodes of each tenant, at the profile service: its businesses (legal
    entities), their registrations and their locations."""

    def exists(self, tenant_id: TenantId, business_id: BusinessId) -> bool:
        """Whether the tenant has a profile node with this id. Raises
        ``ProfileUnavailableError`` when the profile service cannot answer now."""
        ...
