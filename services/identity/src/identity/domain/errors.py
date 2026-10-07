"""Errors of the identity service; the composition root maps them to problem statuses."""

from collections.abc import Mapping
from typing import ClassVar

from domain_kernel.errors import DomainError


class TenantRequiredError(DomainError):
    type_slug: ClassVar[str] = "identity-tenant-required"
    title: ClassVar[str] = "Tenant required for identity"

    def __init__(self) -> None:
        super().__init__("x-tenant-id header required")


class NoticeVersionRequiredError(DomainError):
    type_slug: ClassVar[str] = "consent-notice-version-required"
    title: ClassVar[str] = "Consent needs the notice version"

    def __init__(self, purpose: str) -> None:
        super().__init__(f"granting {purpose} needs the notice_version the person saw")


class ChannelWritesDisabledError(DomainError):
    """No service token is configured, so the channel consent routes refuse every call."""

    type_slug: ClassVar[str] = "identity-channel-writes-disabled"
    title: ClassVar[str] = "Channel consents are not configured"

    def __init__(self) -> None:
        super().__init__("set CW_IDENTITY_CHANNEL_TOKEN to accept channel consents")


class ChannelTokenInvalidError(DomainError):
    type_slug: ClassVar[str] = "identity-channel-token-invalid"
    title: ClassVar[str] = "Service token missing or wrong"

    def __init__(self) -> None:
        super().__init__("channel consents need the x-cw-service-token header with the right token")


class ChannelSubjectInvalidError(DomainError):
    type_slug: ClassVar[str] = "identity-channel-subject-invalid"
    title: ClassVar[str] = "Channel subject is not a phone number"

    def __init__(self, channel: str) -> None:
        super().__init__(f"a {channel} subject must be a phone number in E.164 form")


class ChannelPurposeInvalidError(DomainError):
    type_slug: ClassVar[str] = "identity-channel-purpose-invalid"
    title: ClassVar[str] = "Purpose not recorded on this channel"

    def __init__(self, purpose: str, channel: str, allowed: tuple[str, ...]) -> None:
        super().__init__(
            f"{purpose} cannot be recorded on {channel}; it records {', '.join(allowed)}"
        )


class BillingDisabledError(DomainError):
    type_slug: ClassVar[str] = "billing-disabled"
    title: ClassVar[str] = "Billing provider disabled"

    def __init__(self) -> None:
        super().__init__("billing provider disabled: set CW_BILLING_PROVIDER and its keys")


class InvalidWebhookSignatureError(DomainError):
    type_slug: ClassVar[str] = "billing-webhook-signature-invalid"
    title: ClassVar[str] = "Billing webhook signature invalid"

    def __init__(self) -> None:
        super().__init__("billing webhook signature did not verify")


class RoleNotAllowedError(DomainError):
    """A user was given no role, or a role the tenant's kind does not have (422)."""

    type_slug: ClassVar[str] = "identity-role-not-allowed"
    title: ClassVar[str] = "Role not allowed in this tenant"

    def __init__(self, kind: str, refused: tuple[str, ...]) -> None:
        if refused:
            detail = f"a {kind} tenant has no role {', '.join(refused)}"
        else:
            detail = "a user holds at least one role"
        super().__init__(detail)
        self.kind = kind
        self.refused = refused


class LastAdminError(DomainError):
    """The change would leave the tenant without an active admin (409)."""

    type_slug: ClassVar[str] = "identity-last-admin"
    title: ClassVar[str] = "Tenant would lose its last admin"

    def __init__(self) -> None:
        super().__init__(
            "the tenant needs an active admin: make another user an admin before this change"
        )


class UserNotFoundError(DomainError):
    """No user with this id in the caller's tenant (404)."""

    type_slug: ClassVar[str] = "identity-user-not-found"
    title: ClassVar[str] = "User not found in this tenant"

    def __init__(self, user_id: str) -> None:
        super().__init__(f"no user {user_id} in this tenant")


class UserDisabledError(DomainError):
    """The user is disabled: it cannot sign in and its roles cannot change (403)."""

    type_slug: ClassVar[str] = "identity-user-disabled"
    title: ClassVar[str] = "User is disabled"

    def __init__(self) -> None:
        super().__init__("this user is disabled: it cannot sign in and its roles cannot change")


class SubjectRegisteredError(DomainError):
    """The provider's subject already signs in as a user, in this tenant or another (409)."""

    type_slug: ClassVar[str] = "identity-subject-registered"
    title: ClassVar[str] = "Sign-in already belongs to a user"

    def __init__(self) -> None:
        super().__init__(
            "this sign-in already belongs to a user; exchange it for a session instead"
        )


class ProviderTokenInvalidError(DomainError):
    """The identity provider's token failed a check: signature, issuer, audience, expiry or
    claims (401)."""

    type_slug: ClassVar[str] = "identity-provider-token-invalid"
    title: ClassVar[str] = "Identity provider token is invalid"


class ProviderUnavailableError(DomainError):
    """The identity provider could not be reached, or its keys could not be fetched, so a new
    sign-in fails closed (503)."""

    type_slug: ClassVar[str] = "identity-provider-unavailable"
    title: ClassVar[str] = "Identity provider is unavailable"


class ProviderAccountExistsError(DomainError):
    """The identity provider already has an account for this email address or phone number
    (409)."""

    type_slug: ClassVar[str] = "identity-provider-account-exists"
    title: ClassVar[str] = "Identity provider already has this account"

    def __init__(self) -> None:
        super().__init__(
            "the identity provider already has an account for this address, and an invitation "
            "cannot claim an account it did not create"
        )


class UserNotProvisionedError(DomainError):
    """The provider's subject signs in as no user yet (404). The web treats this as sign-up:
    ``POST /v1/identity/tenants`` creates a tenant with this person as its first user."""

    type_slug: ClassVar[str] = "identity-user-not-provisioned"
    title: ClassVar[str] = "No user for this sign-in yet"

    def __init__(self) -> None:
        super().__init__(
            "this sign-in belongs to no user yet: create a tenant with POST /v1/identity/tenants, "
            "or ask a tenant admin for an invitation"
        )


class MfaRequiredError(DomainError):
    """The user's roles need a second factor and the sign-in had one factor only (403)."""

    type_slug: ClassVar[str] = "identity-mfa-required"
    title: ClassVar[str] = "Second factor required for these roles"

    def __init__(self) -> None:
        super().__init__(
            "these roles sign in with a second factor: verify it at the identity provider "
            "(assurance level aal2) and exchange the new provider token"
        )


class TenantInactiveError(DomainError):
    """The user's tenant was erased, so nobody signs in to it (403)."""

    type_slug: ClassVar[str] = "identity-tenant-inactive"
    title: ClassVar[str] = "Tenant is not active"

    def __init__(self) -> None:
        super().__init__("this tenant was erased; nobody signs in to it")


class TenantDeletingError(DomainError):
    """The tenant asked for its data to be deleted, which is under way: nobody signs in to it and
    it asks for nothing more (403)."""

    type_slug: ClassVar[str] = "identity-tenant-deleting"
    title: ClassVar[str] = "Tenant is being deleted"

    def __init__(self) -> None:
        super().__init__(
            "this tenant asked for its data to be deleted; nobody signs in to it while that "
            "is under way"
        )


class SessionRevokedError(DomainError):
    """The access token names a session version the user no longer has: the user's roles
    changed or the user was disabled after it was issued (401)."""

    type_slug: ClassVar[str] = "identity-session-revoked"
    title: ClassVar[str] = "Session was revoked"
    problem_headers: ClassVar[Mapping[str, str]] = {
        "WWW-Authenticate": 'Bearer error="invalid_token"'
    }

    def __init__(self) -> None:
        super().__init__(
            "this session was revoked when the user's roles changed or the user was disabled; "
            "sign in again"
        )


class ServiceClientInvalidError(DomainError):
    """The client id is unknown or revoked, or the secret is wrong (401)."""

    type_slug: ClassVar[str] = "identity-service-client-invalid"
    title: ClassVar[str] = "Service client or secret is wrong"

    def __init__(self) -> None:
        super().__init__("the client id is unknown or revoked, or the secret is wrong")


class DevSignInUnavailableError(DomainError):
    """The development sign-in answers only with the fake provider in local and test (404)."""

    type_slug: ClassVar[str] = "identity-dev-sign-in-unavailable"
    title: ClassVar[str] = "Development sign-in is not served here"

    def __init__(self) -> None:
        super().__init__(
            "development provider tokens are issued only with CW_AUTH_PROVIDER=fake and CW_ENV "
            "local or test"
        )


class ServiceClientExistsError(DomainError):
    """A service client with this id exists already (409)."""

    type_slug: ClassVar[str] = "identity-service-client-exists"
    title: ClassVar[str] = "Service client exists already"

    def __init__(self, client_id: str) -> None:
        super().__init__(
            f"service client {client_id} exists; revoke it and create the new one under another id"
        )


class ServiceClientNotFoundError(DomainError):
    """No service client with this id (404)."""

    type_slug: ClassVar[str] = "identity-service-client-not-found"
    title: ClassVar[str] = "Service client not found"

    def __init__(self, client_id: str) -> None:
        super().__init__(f"no service client {client_id}")


class TenantNotFoundError(DomainError):
    """The request names a tenant this service does not hold (404)."""

    type_slug: ClassVar[str] = "identity-tenant-not-found"
    title: ClassVar[str] = "Tenant not found"

    def __init__(self) -> None:
        super().__init__("no tenant with this id")


class InternalTenantExistsError(DomainError):
    """The internal tenant exists already; there is one (409)."""

    type_slug: ClassVar[str] = "identity-internal-tenant-exists"
    title: ClassVar[str] = "Internal tenant exists already"

    def __init__(self) -> None:
        super().__init__(
            "the internal tenant exists already; its admins invite the regulatory team"
        )


class SeatLimitReachedError(DomainError):
    """The tenant's plan has no seat left for another user (402). The body carries the limit and
    how many seats are used (``limit``, ``used``), and nothing about who holds them."""

    type_slug: ClassVar[str] = "identity-seat-limit-reached"
    title: ClassVar[str] = "Plan seat limit reached"

    def __init__(self, *, limit: int, used: int) -> None:
        self.limit = limit
        self.used = used
        self.problem_extensions: Mapping[str, object] = {"limit": limit, "used": used}
        super().__init__(
            f"the plan allows {limit} seat(s) and {used} are in use; upgrade the plan or "
            "disable a user first"
        )


class SubscriptionStartPendingError(DomainError):
    """A start under this Idempotency-Key is running, or failed where the provider may have
    created the subscription, so it is never sent to the provider again (409). The billing page
    shows the subscription once the provider's webhook records it; a new start needs a new key."""

    type_slug: ClassVar[str] = "identity-subscription-start-pending"
    title: ClassVar[str] = "A subscription is being created"

    def __init__(self) -> None:
        super().__init__(
            "a subscription is being created for this request; check the billing page before "
            "starting another one"
        )


class DataRequestNotFoundError(DomainError):
    """No request with this id in the tenant; another tenant's is not found either (404)."""

    type_slug: ClassVar[str] = "identity-data-request-not-found"
    title: ClassVar[str] = "Data request not found"

    def __init__(self) -> None:
        super().__init__("the tenant has no data request with this id")


class ExportNotReadyError(DomainError):
    """The request has no export to download: it asks for a deletion, not a copy (409)."""

    type_slug: ClassVar[str] = "identity-export-not-ready"
    title: ClassVar[str] = "No export for this request"

    def __init__(self, kind: str) -> None:
        super().__init__(f"a {kind} request has no export to download")


class TenantNotErasableError(DomainError):
    """The internal tenant, where the regulatory team works, is never erased (422)."""

    type_slug: ClassVar[str] = "identity-tenant-not-erasable"
    title: ClassVar[str] = "This tenant is not erased"

    def __init__(self) -> None:
        super().__init__(
            "the internal tenant holds the regulatory team's accounts and is not erased; "
            "disable its users instead"
        )


class DeletionRequestNotFoundError(DomainError):
    """The tenant has no deletion request still waiting on the services (404)."""

    type_slug: ClassVar[str] = "identity-deletion-request-not-found"
    title: ClassVar[str] = "No open deletion request"

    def __init__(self) -> None:
        super().__init__("the tenant has no deletion request that is not completed")
