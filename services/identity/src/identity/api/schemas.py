"""Request and response bodies of the identity API."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain_kernel.access import MAX_CLIENT_ID_CHARS, Principal, Role, Scope
from identity.application.channel_consents import ChannelConsentSummary
from identity.application.consents import ConsentSummary
from identity.application.sessions import ServiceSession, Session
from identity.application.tenancy import CreatedTenant
from identity.domain.billing import MAX_QUANTITY, PLANS, REGISTRATIONS, SEATS, Plan, Subscription
from identity.domain.channel_consent import (
    MESSAGE_ID_MAX_LENGTH,
    ChannelConsentRecord,
    ConsentChannel,
)
from identity.domain.consent import ConsentPurpose, ConsentRecord, ConsentSource, ConsentState
from identity.domain.entitlements import Entitlements
from identity.domain.tenancy import (
    MAX_NAME_CHARS,
    Tenant,
    TenantKind,
    TenantStatus,
    User,
    UserStatus,
)

E164_PATTERN = r"^\+?[1-9][0-9]{7,14}$"
"""A phone number in E.164 form, the plus optional: the pattern of notification's schema."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsentIn(Strict):
    subject: str = Field(min_length=1, max_length=254, description="User id or E.164 number")
    purpose: ConsentPurpose
    granted: bool = True
    source: ConsentSource
    notice_version: str = Field(default="", max_length=40, description="Required when granting")
    evidence: str = Field(default="", max_length=2000)
    recorded_by: UUID | None = Field(
        default=None,
        description="Who recorded it; ignored when an access token names the caller",
    )


class ConsentOut(BaseModel):
    id: UUID
    subject: str
    purpose: ConsentPurpose
    granted: bool
    source: ConsentSource
    notice_version: str
    evidence: str
    recorded_by: UUID | None
    recorded_at: datetime

    @classmethod
    def from_record(cls, record: ConsentRecord) -> "ConsentOut":
        return cls(
            id=record.id.value,
            subject=record.subject,
            purpose=record.purpose,
            granted=record.granted,
            source=record.source,
            notice_version=record.notice_version,
            evidence=record.evidence,
            recorded_by=None if record.recorded_by is None else record.recorded_by.value,
            recorded_at=record.recorded_at,
        )


class ConsentStateOut(BaseModel):
    purpose: ConsentPurpose
    granted: bool
    notice_version: str
    since: datetime
    source: ConsentSource

    @classmethod
    def from_state(cls, state: ConsentState) -> "ConsentStateOut":
        return cls(
            purpose=state.purpose,
            granted=state.granted,
            notice_version=state.notice_version,
            since=state.since,
            source=state.source,
        )


class ConsentSummaryOut(BaseModel):
    subject: str
    states: list[ConsentStateOut]
    history: list[ConsentOut]

    @classmethod
    def from_summary(cls, summary: ConsentSummary) -> "ConsentSummaryOut":
        return cls(
            subject=summary.subject,
            states=[ConsentStateOut.from_state(state) for state in summary.states],
            history=[ConsentOut.from_record(r) for r in summary.history],
        )


class ChannelConsentIn(Strict):
    channel: ConsentChannel
    subject: str = Field(
        pattern=E164_PATTERN, description="E.164 number; WhatsApp reports it without the plus"
    )
    purpose: ConsentPurpose = Field(description="whatsapp_reminders is the one WhatsApp purpose")
    granted: bool = True
    source: ConsentSource = Field(description="whatsapp_keyword is the one WhatsApp source")
    notice_version: str = Field(default="", max_length=40, description="Required when granting")
    evidence: str = Field(default="", max_length=2000, description="The keyword and the message")
    message_id: str = Field(
        default="",
        max_length=MESSAGE_ID_MAX_LENGTH,
        description="The channel's message id; the same id again returns the first record",
    )


class ChannelConsentOut(BaseModel):
    id: UUID
    channel: ConsentChannel
    subject: str
    purpose: ConsentPurpose
    granted: bool
    source: ConsentSource
    notice_version: str
    evidence: str
    message_id: str
    recorded_at: datetime

    @classmethod
    def from_record(cls, record: ChannelConsentRecord) -> "ChannelConsentOut":
        return cls(
            id=record.id.value,
            channel=record.channel,
            subject=record.subject,
            purpose=record.purpose,
            granted=record.granted,
            source=record.source,
            notice_version=record.notice_version,
            evidence=record.evidence,
            message_id=record.message_id,
            recorded_at=record.recorded_at,
        )


class ChannelConsentSummaryOut(BaseModel):
    channel: ConsentChannel
    subject: str
    states: list[ConsentStateOut]
    history: list[ChannelConsentOut]

    @classmethod
    def from_summary(cls, summary: ChannelConsentSummary) -> "ChannelConsentSummaryOut":
        return cls(
            channel=summary.channel,
            subject=summary.subject,
            states=[ConsentStateOut.from_state(state) for state in summary.states],
            history=[ChannelConsentOut.from_record(record) for record in summary.history],
        )


class LimitsOut(BaseModel):
    registrations: int | None = Field(
        description="GSTIN registrations across the tenant's businesses; null is no limit"
    )
    seats: int | None = Field(description="Active users; null is no limit")


class PlanOut(BaseModel):
    key: str
    name: str
    amount_paise: int
    period: str
    description: str
    limits: LimitsOut = Field(
        description="What one unit of the plan's quantity allows (placeholders until decided)"
    )

    @classmethod
    def from_plan(cls, plan: Plan) -> "PlanOut":
        return cls(
            key=plan.key,
            name=plan.name,
            amount_paise=plan.amount_paise,
            period=plan.period.value,
            description=plan.description,
            limits=LimitsOut(
                registrations=plan.limit(REGISTRATIONS, 1), seats=plan.limit(SEATS, 1)
            ),
        )


class SubscriptionIn(Strict):
    plan_key: str = Field(pattern="^(" + "|".join(PLANS) + ")$")
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=200)
    quantity: int = Field(
        default=1,
        ge=1,
        le=MAX_QUANTITY,
        description="Units of the plan: businesses for the owner plan, seats for the CA plan",
    )


class SubscriptionOut(BaseModel):
    plan_key: str
    provider_subscription_id: str
    status: str
    started_at: datetime
    checkout_url: str
    quantity: int

    @classmethod
    def from_subscription(cls, subscription: Subscription) -> "SubscriptionOut":
        return cls(
            plan_key=subscription.plan_key,
            provider_subscription_id=subscription.provider_subscription_id,
            status=subscription.status.value,
            started_at=subscription.started_at,
            checkout_url=subscription.checkout_url,
            quantity=subscription.quantity,
        )


class WebhookOut(BaseModel):
    kind: str
    provider_subscription_id: str
    status: str | None
    ignored: bool = Field(
        default=False,
        description=(
            "Nothing changed: the webhook names no tenant, or a subscription the tenant does "
            "not hold and may not adopt, or it is older than the last event applied, or follows "
            "a cancellation"
        ),
    )
    duplicate: bool = Field(
        default=False, description="The same body was received before; nothing changed"
    )


class EntitlementsOut(BaseModel):
    plan_key: str = Field(description="The current plan; free without a paid subscription")
    status: str = Field(description="The subscription's status, or free")
    limits: LimitsOut
    enforced: bool = Field(
        description="Whether going over the limits is refused (the flag identity.plan_limits)"
    )

    @classmethod
    def from_entitlements(cls, entitlements: Entitlements) -> "EntitlementsOut":
        return cls(
            plan_key=entitlements.plan_key,
            status=entitlements.status,
            limits=LimitsOut(
                registrations=entitlements.limits.registrations, seats=entitlements.limits.seats
            ),
            enforced=entitlements.enforced,
        )


# ---------------------------------------------------------------- sign-in and tokens

PROVIDER_TOKEN_MAX_CHARS = 8192
CLIENT_ID_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class SessionIn(Strict):
    provider_token: str = Field(
        min_length=1,
        max_length=PROVIDER_TOKEN_MAX_CHARS,
        description="The identity provider's token for the person who signed in",
    )


class SessionOut(BaseModel):
    access_token: str = Field(description="An ES256 access token; send it as a bearer token")
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(description="Seconds until the token expires")
    tenant_id: UUID
    user_id: UUID
    roles: list[Role]
    mfa: bool = Field(description="Whether the person signed in with a second factor")

    @classmethod
    def from_session(cls, session: Session) -> "SessionOut":
        principal = session.principal
        return cls(
            access_token=session.token.token,
            expires_in=session.token.expires_in,
            tenant_id=session.tenant.id.value,
            user_id=session.user.id.value,
            roles=sorted(principal.roles),
            mfa=principal.mfa,
        )


class ServiceTokenIn(Strict):
    client_id: str = Field(min_length=1, max_length=MAX_CLIENT_ID_CHARS, pattern=CLIENT_ID_PATTERN)
    client_secret: str = Field(min_length=1, max_length=256)


class ServiceTokenOut(BaseModel):
    access_token: str = Field(description="An ES256 access token; send it as a bearer token")
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(description="Seconds until the token expires")
    scopes: list[Scope]

    @classmethod
    def from_session(cls, session: ServiceSession) -> "ServiceTokenOut":
        return cls(
            access_token=session.token.token,
            expires_in=session.token.expires_in,
            scopes=sorted(session.principal.scopes),
        )


class JwkOut(BaseModel):
    """One public signing key (RFC 7517): an EC key on the P-256 curve."""

    kty: str
    crv: str
    x: str
    y: str
    kid: str
    use: str
    alg: str


class JwksOut(BaseModel):
    keys: list[JwkOut]


class TenantOut(BaseModel):
    id: UUID
    kind: TenantKind
    name: str
    region: str
    status: TenantStatus
    created_at: datetime

    @classmethod
    def from_tenant(cls, tenant: Tenant) -> "TenantOut":
        return cls(
            id=tenant.id.value,
            kind=tenant.kind,
            name=tenant.name,
            region=tenant.region,
            status=tenant.status,
            created_at=tenant.created_at,
        )


class UserOut(BaseModel):
    id: UUID
    tenant_id: UUID
    email: str
    phone: str
    display_name: str
    roles: list[Role]
    status: UserStatus
    session_version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(
            id=user.id.value,
            tenant_id=user.tenant_id.value,
            email=user.contact.email,
            phone=user.contact.phone,
            display_name=user.display_name,
            roles=sorted(user.roles),
            status=user.status,
            session_version=user.session_version,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class MembershipOut(BaseModel):
    """A user's membership of the tenant: their roles and whether they may still sign in, and
    nothing that reaches them (no contact details)."""

    user_id: UUID
    tenant_id: UUID
    roles: list[Role]
    status: UserStatus

    @classmethod
    def from_user(cls, user: User) -> "MembershipOut":
        return cls(
            user_id=user.id.value,
            tenant_id=user.tenant_id.value,
            roles=sorted(user.roles),
            status=user.status,
        )


class MeOut(BaseModel):
    """The signed-in user as the access token names them, checked against the store."""

    kind: Literal["user"] = "user"
    user_id: UUID
    tenant: TenantOut
    roles: list[Role]
    session_version: int
    mfa: bool = Field(description="Whether the person signed in with a second factor")
    email: str
    phone: str
    display_name: str

    @classmethod
    def from_session(cls, principal: Principal, tenant: Tenant, user: User) -> "MeOut":
        return cls(
            user_id=user.id.value,
            tenant=TenantOut.from_tenant(tenant),
            roles=sorted(principal.roles),
            session_version=principal.session_version,
            mfa=principal.mfa,
            email=user.contact.email,
            phone=user.contact.phone,
            display_name=user.display_name,
        )


class DevProviderTokenIn(Strict):
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)
    phone: str | None = Field(default=None, pattern=E164_PATTERN, description="E.164 number")
    aal: Literal["aal1", "aal2"] = Field(
        default="aal1", description="aal2 stands for a sign-in with a second factor"
    )

    @model_validator(mode="after")
    def _one_contact(self) -> "DevProviderTokenIn":
        if not self.email and not self.phone:
            raise ValueError("give the email address or the phone number to sign in with")
        return self


class DevProviderTokenOut(BaseModel):
    provider_token: str = Field(description="A fake provider token for POST /v1/identity/sessions")
    subject: str


class TenantIn(Strict):
    kind: Literal["business", "ca_firm"]
    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    provider_token: str = Field(
        min_length=1,
        max_length=PROVIDER_TOKEN_MAX_CHARS,
        description="The identity provider's token of the person signing up",
    )
    display_name: str = Field(default="", max_length=MAX_NAME_CHARS)


class CreatedTenantOut(BaseModel):
    tenant: TenantOut
    user: UserOut
    session: SessionOut

    @classmethod
    def from_created(cls, created: CreatedTenant) -> "CreatedTenantOut":
        return cls(
            tenant=TenantOut.from_tenant(created.tenant),
            user=UserOut.from_user(created.user),
            session=SessionOut.from_session(created.session),
        )


# ---------------------------------------------------------------- tenant admin


class InviteIn(Strict):
    email: str | None = Field(default=None, max_length=254, pattern=EMAIL_PATTERN)
    phone: str | None = Field(default=None, pattern=E164_PATTERN, description="E.164 number")
    display_name: str = Field(default="", max_length=MAX_NAME_CHARS)
    roles: list[Role] = Field(
        min_length=1, description="Roles the tenant's kind allows; at least one"
    )

    @model_validator(mode="after")
    def _one_contact(self) -> "InviteIn":
        if not self.email and not self.phone:
            raise ValueError("give the email address or the phone number to invite")
        return self


class RolesIn(Strict):
    roles: list[Role] = Field(
        min_length=1, description="The roles the user holds instead; the tenant's kind allows them"
    )


class UsersOut(BaseModel):
    items: list[UserOut] = Field(description="The tenant's users, oldest first")
