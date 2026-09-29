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
