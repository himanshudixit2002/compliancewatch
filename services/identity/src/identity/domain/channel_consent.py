"""Channel consents: an opt-in or opt-out typed on a channel, keyed by the number that sent it.

A person who writes START to the WhatsApp number has not signed in, and no tenant owns their
number yet, so these records carry no tenant. Each one is the evidence of what a number asked
for, under which notice, in which message. They are append-only like ``consent_record``: a
withdrawal is a record with ``granted`` false, and the latest record per purpose is the current
state. The channel's message id makes a redelivered webhook find the record it made the first
time instead of writing a second one.

The subject is kept in the form WhatsApp reports it: the E.164 digits without the plus, so a
number written either way is one subject.
"""

import re
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Protocol

from domain_kernel._validation import require_aware, require_bool, require_instance, require_text
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import ConsentId
from identity.domain.consent import ConsentPurpose, ConsentSource
from identity.domain.errors import ChannelPurposeInvalidError, ChannelSubjectInvalidError

E164: Final = re.compile(r"\+?[1-9][0-9]{7,14}")
"""A phone number in E.164 form, the plus optional: the pattern of notification's schema."""

MESSAGE_ID_MAX_LENGTH: Final = 255


class ConsentChannel(StrEnum):
    WHATSAPP = "whatsapp"


CHANNEL_PURPOSES: Final[Mapping[ConsentChannel, tuple[ConsentPurpose, ...]]] = MappingProxyType(
    {ConsentChannel.WHATSAPP: (ConsentPurpose.WHATSAPP_REMINDERS,)}
)
"""The purposes a channel can grant or withdraw: a WhatsApp keyword answers for WhatsApp
reminders and nothing else."""

CHANNEL_SOURCES: Final[Mapping[ConsentChannel, tuple[ConsentSource, ...]]] = MappingProxyType(
    {ConsentChannel.WHATSAPP: (ConsentSource.WHATSAPP_KEYWORD,)}
)
"""How a consent reaches us on each channel."""


def channel_subject(channel: ConsentChannel, text: str) -> str:
    """The subject ``text`` names on ``channel``: its E.164 digits without the plus."""
    require_instance(channel, ConsentChannel, "channel")
    if not isinstance(text, str) or E164.fullmatch(text) is None:
        raise ChannelSubjectInvalidError(channel.value)
    return text.removeprefix("+")


def require_channel_purpose(channel: ConsentChannel, purpose: ConsentPurpose) -> ConsentPurpose:
    """``purpose`` when ``channel`` can record it."""
    require_instance(purpose, ConsentPurpose, "purpose")
    allowed = CHANNEL_PURPOSES[channel]
    if purpose not in allowed:
        raise ChannelPurposeInvalidError(
            purpose.value, channel.value, tuple(item.value for item in allowed)
        )
    return purpose


@dataclass(frozen=True, slots=True)
class ChannelConsentRecord:
    id: ConsentId
    channel: ConsentChannel
    subject: str
    """The number's E.164 digits without the plus."""
    purpose: ConsentPurpose
    granted: bool
    source: ConsentSource
    recorded_at: datetime
    notice_version: str = ""
    evidence: str = ""
    message_id: str = ""
    """The channel's id of the message that carried the keyword; empty when there was none."""

    def __post_init__(self) -> None:
        require_instance(self.id, ConsentId, "id")
        require_instance(self.channel, ConsentChannel, "channel")
        if channel_subject(self.channel, self.subject) != self.subject:
            raise InvariantViolationError("subject must be the number's digits without the plus")
        require_channel_purpose(self.channel, self.purpose)
        require_bool(self.granted, "granted")
        require_instance(self.source, ConsentSource, "source")
        if self.source not in CHANNEL_SOURCES[self.channel]:
            raise InvariantViolationError(
                f"source {self.source.value} does not record consents on {self.channel.value}"
            )
        require_aware(self.recorded_at, "recorded_at")
        require_instance(self.notice_version, str, "notice_version")
        if self.granted and not self.notice_version.strip():
            raise InvariantViolationError("a grant must carry the notice_version the person saw")
        require_instance(self.evidence, str, "evidence")
        require_instance(self.message_id, str, "message_id")
        if self.message_id:
            require_text(self.message_id, "message_id")
            if len(self.message_id) > MESSAGE_ID_MAX_LENGTH:
                raise InvariantViolationError(
                    f"message_id must be at most {MESSAGE_ID_MAX_LENGTH} characters"
                )


class ChannelConsentRepository(Protocol):
    def add(self, record: ChannelConsentRecord) -> ChannelConsentRecord:
        """Store ``record`` and return it. When a record with the same channel and message id
        is stored already, store nothing and return that record."""
        ...

    def by_message(self, channel: ConsentChannel, message_id: str) -> ChannelConsentRecord | None:
        """The record made from one message of the channel, if any."""
        ...

    def history(
        self, channel: ConsentChannel, subject: str, purpose: ConsentPurpose | None = None
    ) -> list[ChannelConsentRecord]:
        """Oldest first."""
        ...


class ChannelUnitOfWork(Protocol):
    @property
    def channel_consents(self) -> ChannelConsentRepository: ...


class ChannelUnitOfWorkFactory(Protocol):
    """Opens one transaction. There is no tenant: no tenant owns the number yet."""

    def __call__(self) -> AbstractContextManager[ChannelUnitOfWork]: ...
