"""What a recipient has agreed to and when they may be disturbed.

A preference is per channel and recipient (an E.164 phone number for WhatsApp, an address for
email). Nobody receives a business-initiated message without ``opted_in``; an opt-out is
honoured from the moment it is recorded. Quiet hours are a window in Indian Standard Time
during which a message is held and sent at the window's end (guide section 7, F9).
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Protocol, Self

from domain_kernel._validation import require_aware, require_bool, require_instance, require_text
from domain_kernel.channels import Channel

IST = timezone(timedelta(hours=5, minutes=30), "IST")


class ConsentSource(StrEnum):
    """How the opt-in or opt-out reached us."""

    WHATSAPP_KEYWORD = "whatsapp_keyword"
    WEB_ONBOARDING = "web_onboarding"
    API = "api"
    SUPPORT = "support"


@dataclass(frozen=True, slots=True)
class QuietHours:
    """``start`` to ``end`` in IST; a window that crosses midnight is allowed (21:00 to 08:00)."""

    start: time
    end: time

    def __post_init__(self) -> None:
        require_instance(self.start, time, "start")
        require_instance(self.end, time, "end")

    @classmethod
    def parse(cls, start: str, end: str) -> Self:
        return cls(time.fromisoformat(start), time.fromisoformat(end))

    def is_quiet(self, at: datetime) -> bool:
        local = require_aware(at, "at").astimezone(IST).time()
        if self.start == self.end:
            return False
        if self.start < self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end

    def next_allowed(self, at: datetime) -> datetime:
        """``at`` itself outside the window, otherwise the moment the window ends."""
        if not self.is_quiet(at):
            return at
        local = at.astimezone(IST)
        end = local.replace(hour=self.end.hour, minute=self.end.minute, second=0, microsecond=0)
        if end <= local:
            end += timedelta(days=1)
        return end.astimezone(at.tzinfo)


DEFAULT_QUIET_HOURS = QuietHours(time(21, 0), time(8, 0))


@dataclass(frozen=True, slots=True)
class ChannelPreference:
    channel: Channel
    recipient: str
    opted_in: bool
    source: ConsentSource
    updated_at: datetime
    language: str = "en"
    quiet_hours: QuietHours = DEFAULT_QUIET_HOURS

    def __post_init__(self) -> None:
        require_instance(self.channel, Channel, "channel")
        require_text(self.recipient, "recipient")
        require_bool(self.opted_in, "opted_in")
        require_instance(self.source, ConsentSource, "source")
        require_aware(self.updated_at, "updated_at")
        require_text(self.language, "language")
        require_instance(self.quiet_hours, QuietHours, "quiet_hours")


class PreferenceRepository(Protocol):
    def get(self, channel: Channel, recipient: str) -> ChannelPreference | None: ...

    def save(self, preference: ChannelPreference) -> None: ...
