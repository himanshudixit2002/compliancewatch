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
