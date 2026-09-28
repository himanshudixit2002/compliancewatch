"""Errors of the notification service; the composition root maps them to problem statuses."""

from typing import ClassVar

from domain_kernel.errors import DomainError


class UnknownTemplateError(DomainError):
    type_slug: ClassVar[str] = "notification-template-unknown"
    title: ClassVar[str] = "Notification template not found"

    def __init__(self, key: str, language: str) -> None:
        super().__init__(f"no template {key!r} for language {language!r}")


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
