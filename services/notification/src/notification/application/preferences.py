"""Record an opt-in or opt-out and read a preference back."""

from collections.abc import Callable
from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from notification.domain.preferences import (
    DEFAULT_QUIET_HOURS,
    ChannelPreference,
    ConsentSource,
    PreferenceRepository,
    QuietHours,
)


class SetOptIn:
    def __init__(
        self, preferences: PreferenceRepository, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._preferences = preferences
        self._clock = clock

    def run(
        self,
        channel: Channel,
        recipient: str,
        *,
        opted_in: bool,
        source: ConsentSource,
        language: str | None = None,
        quiet_hours: QuietHours | None = None,
    ) -> ChannelPreference:
        existing = self._preferences.get(channel, recipient)
        preference = ChannelPreference(
            channel=channel,
            recipient=recipient,
            opted_in=opted_in,
            source=source,
            updated_at=self._clock(),
            language=language or (existing.language if existing else "en"),
            quiet_hours=quiet_hours or (existing.quiet_hours if existing else DEFAULT_QUIET_HOURS),
        )
        self._preferences.save(preference)
        return preference
