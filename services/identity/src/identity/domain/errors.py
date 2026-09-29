"""Errors of the identity service; the composition root maps them to problem statuses."""

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
