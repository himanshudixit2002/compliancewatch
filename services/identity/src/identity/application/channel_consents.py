"""Record a consent typed on a channel, and answer what a number has agreed to.

``RecordChannelConsent`` is what the WhatsApp bot calls when a person writes an opt-in or
opt-out keyword. A grant needs the notice version the person was shown, as for any consent.
The call is idempotent on the channel's message id: Meta redelivers a webhook it thinks was
lost, and the second delivery gets back the record the first one made.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from domain_kernel.events import utc_now
from domain_kernel.ids import ConsentId
from identity.domain.channel_consent import (
    ChannelConsentRecord,
    ChannelUnitOfWorkFactory,
    ConsentChannel,
    channel_subject,
    require_channel_purpose,
)
from identity.domain.consent import ConsentPurpose, ConsentSource, ConsentState
from identity.domain.errors import NoticeVersionRequiredError


@dataclass(frozen=True, slots=True)
class RecordedChannelConsent:
    record: ChannelConsentRecord
    created: bool
    """False when the message had been recorded already and ``record`` is that first record."""


@dataclass(frozen=True, slots=True)
class ChannelConsentSummary:
    channel: ConsentChannel
    subject: str
    states: tuple[ConsentState, ...]
    history: tuple[ChannelConsentRecord, ...]

    def granted(self, purpose: ConsentPurpose) -> bool:
        return any(state.purpose is purpose and state.granted for state in self.states)


class RecordChannelConsent:
    def __init__(
        self, unit_of_work: ChannelUnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock

    def run(
        self,
        channel: ConsentChannel,
        subject: str,
        purpose: ConsentPurpose,
        *,
        granted: bool,
        source: ConsentSource,
        notice_version: str = "",
        evidence: str = "",
        message_id: str = "",
    ) -> RecordedChannelConsent:
        number = channel_subject(channel, subject)
        require_channel_purpose(channel, purpose)
        if granted and not notice_version.strip():
            raise NoticeVersionRequiredError(purpose.value)
        message = message_id.strip()
        with self._unit_of_work() as uow:
            if message:
                existing = uow.channel_consents.by_message(channel, message)
                if existing is not None:
                    return RecordedChannelConsent(existing, created=False)
            record = ChannelConsentRecord(
                id=ConsentId.new(),
                channel=channel,
                subject=number,
                purpose=purpose,
                granted=granted,
                source=source,
                recorded_at=self._clock(),
                notice_version=notice_version.strip(),
                evidence=evidence,
                message_id=message,
            )
            stored = uow.channel_consents.add(record)
        return RecordedChannelConsent(stored, created=stored.id == record.id)


class ChannelConsentStatus:
    def __init__(self, unit_of_work: ChannelUnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, channel: ConsentChannel, subject: str) -> ChannelConsentSummary:
        number = channel_subject(channel, subject)
        with self._unit_of_work() as uow:
            history = tuple(uow.channel_consents.history(channel, number))
        latest: dict[ConsentPurpose, ChannelConsentRecord] = {}
        for record in history:
            latest[record.purpose] = record
        states = tuple(
            ConsentState(
                purpose=record.purpose,
                granted=record.granted,
                notice_version=record.notice_version,
                since=record.recorded_at,
                source=record.source,
            )
            for record in latest.values()
        )
        return ChannelConsentSummary(channel, number, states, history)
