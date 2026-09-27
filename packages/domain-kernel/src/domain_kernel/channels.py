"""Notification channels."""

from enum import StrEnum


class Channel(StrEnum):
    """Where a notification is delivered."""

    WHATSAPP = "whatsapp"
    EMAIL = "email"
