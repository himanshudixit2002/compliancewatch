"""Response bodies of the audit trail route."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from domain_kernel.audit import AuditEntry, AuditEntryId
from identity.domain.audit import AuditKey, plain_json


class AuditSubjectOut(BaseModel):
    type: str = Field(description="What was acted on, a snake_case noun: user, rule_version")
    id: str = Field(description="Its id")


class AuditActorOut(BaseModel):
    kind: Literal["user", "service", "system"]
    id: str = Field(description="A user id, a service client id, or the service that acted")
    label: str = Field(
        description="A user's roles, service:<client> or system:<service>; never a name"
    )


class AuditEntryOut(BaseModel):
    """One audited action, as ``audit.event`` keeps it: personal identifiers in the reason and
    in before and after are masked ([PAN], [GSTIN], [PHONE], [EMAIL], [AADHAAR])."""

    id: UUID
    action: str = Field(description="<subject_type>.<verb>, such as user.roles_changed")
    tenant_id: UUID | None = Field(description="The tenant whose data it touched; null: platform")
    subject: AuditSubjectOut
    actor: AuditActorOut
    reason: str = Field(description="Why, as the person said; empty when none was asked")
    before: dict[str, Any] | None = Field(description="What the action changed, as it was")
    after: dict[str, Any] | None = Field(description="What the action changed, as it is now")
    occurred_at: datetime
    correlation_id: str | None = Field(description="The request or event behind the action")

    @classmethod
    def from_entry(cls, entry: AuditEntry) -> "AuditEntryOut":
        return cls(
            id=entry.entry_id.value,
            action=entry.action,
            tenant_id=None if entry.tenant_id is None else entry.tenant_id.value,
            subject=AuditSubjectOut(type=entry.subject_type, id=entry.subject_id),
            actor=AuditActorOut(
                kind=entry.actor.kind.value, id=entry.actor.id, label=entry.actor.label
            ),
            reason=entry.reason,
            before=plain_json(entry.before),
            after=plain_json(entry.after),
            occurred_at=entry.occurred_at,
            correlation_id=entry.correlation_id,
        )


class AuditKeyset(BaseModel):
    """The cursor's keyset: the last entry of a page. A time with no zone is not one this route
    issued, so it is refused as a bad cursor."""

    at: AwareDatetime
    id: UUID

    @classmethod
    def of(cls, entry: AuditEntry) -> "AuditKeyset":
        return cls(at=entry.occurred_at, id=entry.entry_id.value)

    def key(self) -> AuditKey:
        return AuditKey(self.at, AuditEntryId(self.id))
