"""Record an opt-in or opt-out and read a preference back, by normalised address."""

from collections.abc import Callable
from datetime import datetime

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from notification.domain.addresses import normalise_address
from notification.domain.preferences import (
    DEFAULT_QUIET_HOURS,
    ChannelPreference,
    ConsentSource,
    QuietHours,
)
from notification.domain.repository import UnitOfWorkFactory


class SetOptIn:
    """A new opt-in or opt-out replaces the address's consent. Language and quiet hours carry
    over from the previous record unless the new one gives them."""

    def __init__(
        self, unit_of_work: UnitOfWorkFactory, *, clock: Callable[[], datetime] = utc_now
    ) -> None:
        self._unit_of_work = unit_of_work
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
        address = normalise_address(channel, recipient)
        with self._unit_of_work.shared() as unit:
            existing = unit.preferences.get(channel, address)
            preference = ChannelPreference(
                channel=channel,
                address=address,
                opted_in=opted_in,
                source=source,
                updated_at=self._clock(),
                language=language or (existing.language if existing else "en"),
                quiet_hours=quiet_hours
                or (existing.quiet_hours if existing else DEFAULT_QUIET_HOURS),
            )
            unit.preferences.save(preference)
        return preference


class GetPreference:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, channel: Channel, recipient: str) -> ChannelPreference | None:
        """The address's recorded consent; None when it never opted in or out."""
        address = normalise_address(channel, recipient)
        with self._unit_of_work.shared() as unit:
            return unit.preferences.get(channel, address)
