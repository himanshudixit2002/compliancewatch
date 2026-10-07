"""Record an opt-in or opt-out and read a preference back, by normalised address.

An opt-in given on the web (source ``web_onboarding`` or ``web_settings``) is recorded only when
identity holds the subject's granted consent for the channel's purpose in the tenant
(``SetPreference``): ``whatsapp_reminders`` for WhatsApp, ``email_reminders`` for email. The
web records that consent first, with the user id as the subject, so a preference never says yes
where no consent says so (docs/legal/data-map.md). Opt-outs and the other sources (the WhatsApp
keyword, the API, support) are recorded as they come.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from notification.domain.addresses import normalise_address
from notification.domain.errors import (
    ConsentNotRecordedError,
    ConsentSubjectRequiredError,
    TenantRequiredError,
)
from notification.domain.ports import ConsentReader
from notification.domain.preferences import (
    DEFAULT_QUIET_HOURS,
    ChannelPreference,
    ConsentSource,
    QuietHours,
)
from notification.domain.repository import UnitOfWorkFactory

CONSENT_PURPOSES: Final[dict[Channel, str]] = {
    Channel.WHATSAPP: "whatsapp_reminders",
    Channel.EMAIL: "email_reminders",
}
"""The identity ``ConsentPurpose`` that covers reminders on each channel."""
WEB_SOURCES: Final = frozenset({ConsentSource.WEB_ONBOARDING, ConsentSource.WEB_SETTINGS})


def needs_consent(opted_in: bool, source: ConsentSource) -> bool:
    """Whether the change is a web opt-in, which identity's consent must cover."""
    return opted_in and source in WEB_SOURCES


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


class SetPreference:
    """The preferences route's use case: ``SetOptIn`` once a web opt-in is known to be covered.

    For a web opt-in the tenant and the consent subject are required (``TenantRequiredError``,
    ``ConsentSubjectRequiredError``); the address is checked before identity is asked, and a
    consent that is not recorded or not granted is ``ConsentNotRecordedError``. Nothing is saved
    unless the check passes, and an identity that cannot answer (``DependencyUnavailableError``)
    saves nothing either. Any other change goes straight to ``SetOptIn``, the tenant and subject
    unused."""

    def __init__(self, set_opt_in: SetOptIn, consents: ConsentReader) -> None:
        self._set_opt_in = set_opt_in
        self._consents = consents

    def run(
        self,
        channel: Channel,
        recipient: str,
        *,
        opted_in: bool,
        source: ConsentSource,
        language: str | None = None,
        quiet_hours: QuietHours | None = None,
        tenant_id: TenantId | None = None,
        subject: str | None = None,
    ) -> ChannelPreference:
        if needs_consent(opted_in, source):
            if tenant_id is None:
                raise TenantRequiredError()
            if not subject:
                raise ConsentSubjectRequiredError()
            normalise_address(channel, recipient)
            purpose = CONSENT_PURPOSES[channel]
            if not self._consents.granted(tenant_id, subject, purpose):
                raise ConsentNotRecordedError(purpose)
        return self._set_opt_in.run(
            channel,
            recipient,
            opted_in=opted_in,
            source=source,
            language=language,
            quiet_hours=quiet_hours,
        )


class GetPreference:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, channel: Channel, recipient: str) -> ChannelPreference | None:
        """The address's recorded consent; None when it never opted in or out."""
        address = normalise_address(channel, recipient)
        with self._unit_of_work.shared() as unit:
            return unit.preferences.get(channel, address)
