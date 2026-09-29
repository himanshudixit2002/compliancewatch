"""Errors of the notification service; the composition root maps them to problem statuses."""

from typing import ClassVar

from domain_kernel.errors import DomainError


class TenantRequiredError(DomainError):
    type_slug: ClassVar[str] = "notification-tenant-required"
    title: ClassVar[str] = "Tenant required for notification"

    def __init__(self) -> None:
        super().__init__("x-tenant-id header required")


class UnknownTemplateError(DomainError):
    type_slug: ClassVar[str] = "notification-template-unknown"
    title: ClassVar[str] = "Notification template not found"

    def __init__(self, key: str, language: str | None = None) -> None:
        where = "" if language is None else f" for language {language!r}"
        super().__init__(f"no template {key!r}{where}")


class MissingPlaceholderError(DomainError):
    type_slug: ClassVar[str] = "notification-template-placeholder-missing"
    title: ClassVar[str] = "Notification template placeholder missing"

    def __init__(self, key: str, placeholder: str) -> None:
        super().__init__(f"template {key!r} needs a value for {placeholder!r}")


class UnknownChannelError(DomainError):
    type_slug: ClassVar[str] = "notification-channel-unknown"
    title: ClassVar[str] = "Notification channel not wired"

    def __init__(self, channel: str) -> None:
        super().__init__(f"no channel adapter for {channel!r}")


class InvalidAddressError(DomainError):
    """A phone number or email address that cannot be normalised. The detail names the channel
    and the rule it breaks, never the address itself, which is personal data."""

    type_slug: ClassVar[str] = "notification-address-invalid"
    title: ClassVar[str] = "Notification address invalid"

    def __init__(self, channel: str, reason: str) -> None:
        super().__init__(f"not a valid {channel} address: {reason}")
