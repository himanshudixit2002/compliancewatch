"""Errors of the notification service; the composition root maps them to problem statuses."""

from collections.abc import Mapping
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


class RecipientNotFoundError(DomainError):
    type_slug: ClassVar[str] = "notification-recipient-not-found"
    title: ClassVar[str] = "Notification recipient not found"

    def __init__(self, recipient_id: str) -> None:
        super().__init__(f"no recipient {recipient_id} in this tenant")


class DependencyUnavailableError(DomainError):
    """A service the notification service reads from, such as the rulebook, did not answer."""

    type_slug: ClassVar[str] = "notification-dependency-unavailable"
    title: ClassVar[str] = "Notification dependency unavailable"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class DependencyRefusedError(DomainError):
    """A service the notification service reads from refused the read for a reason another try
    would meet again, such as the rulebook answering 403 to the reader's credentials."""

    type_slug: ClassVar[str] = "notification-dependency-refused"
    title: ClassVar[str] = "Notification dependency refused the read"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)


class NotificationNotFoundError(DomainError):
    type_slug: ClassVar[str] = "notification-not-found"
    title: ClassVar[str] = "Notification not found"

    def __init__(self, notification_id: str) -> None:
        super().__init__(f"no notification {notification_id} in this tenant")


class ResendNotAllowedError(DomainError):
    """Only a notification that failed for good can be sent again."""

    type_slug: ClassVar[str] = "notification-resend-not-allowed"
    title: ClassVar[str] = "Notification cannot be sent again"

    def __init__(self, notification_id: str, state: str) -> None:
        super().__init__(f"notification {notification_id} is {state}; only a failed one is resent")


class ReceiptsDisabledError(DomainError):
    """The receipt routes fail closed: without a configured token nothing is accepted."""

    type_slug: ClassVar[str] = "notification-receipts-disabled"
    title: ClassVar[str] = "Notification receipts disabled"

    def __init__(self, setting: str = "CW_NOTIFICATION_BOT_TOKEN") -> None:
        super().__init__(f"delivery receipts are refused until {setting} is set")


class ReceiptTokenInvalidError(DomainError):
    type_slug: ClassVar[str] = "notification-receipt-token-invalid"
    title: ClassVar[str] = "Notification receipt token invalid"

    def __init__(self) -> None:
        super().__init__("missing or wrong receipt token")


class EmailFeedbackInvalidError(DomainError):
    """A body on the email feedback route that is not a verified SNS message of the expected
    topic: not JSON, a field missing, a signing certificate outside SNS, a signature version
    other than 2, a signature that does not verify, or another topic."""

    type_slug: ClassVar[str] = "notification-email-feedback-invalid"
    title: ClassVar[str] = "Email feedback not a verified SNS message"

    def __init__(self, reason: str) -> None:
        super().__init__(f"email feedback refused: {reason}")


class EmailFeedbackUnauthorizedError(DomainError):
    """The email feedback route takes SNS's HTTP basic credentials; the challenge header makes
    SNS send them."""

    type_slug: ClassVar[str] = "notification-email-feedback-unauthorized"
    title: ClassVar[str] = "Email feedback credentials missing or wrong"
    problem_headers: ClassVar[Mapping[str, str]] = {
        "WWW-Authenticate": 'Basic realm="notification-email-feedback"'
    }

    def __init__(self) -> None:
        super().__init__("missing or wrong basic credentials")
