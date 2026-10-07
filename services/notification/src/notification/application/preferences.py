"""Record an opt-in or opt-out and read a preference back, by normalised address.

An opt-in given on the web (source ``web_onboarding`` or ``web_settings``) is recorded only when
identity holds the subject's granted consent for the channel's purpose in the tenant
(``SetPreference``): ``whatsapp_reminders`` for WhatsApp, ``email_reminders`` for email; and,
where identity knows the subject's contact on the channel (a user's phone or email), only for
that address. The web records that consent first, with the user id as the subject, so a
preference never says yes where no consent says so (docs/legal/data-map.md). Opt-outs and the
other sources (the WhatsApp keyword, the API, support) are recorded as they come.

The trust boundary: the consent subject comes from the caller, the web app's server, which holds
the notification:preferences scope and names the signed-in user; no user token reaches this
route. Identity checks that the subject's consent exists and that the address is theirs when it
knows their contact; it cannot tell that the person behind the subject is the one at the web app.
The ``api`` and ``support`` sources skip the consent check, so outside header mode only a service
token records them (the route refuses an anonymous caller).

A preference set on the web names the tenant it was set for (``set_for_tenant``); any other
source names none. That tenant's data export shows the preference, and no other tenant's does.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from domain_kernel.ids import TenantId
from notification.domain.addresses import normalise_address
from notification.domain.errors import (
    ConsentAddressNotTheirsError,
    ConsentNotRecordedError,
    ConsentSubjectRequiredError,
    TenantRequiredError,
)
from notification.domain.ports import ConsentReader
from notification.domain.preferences import (
    DEFAULT_QUIET_HOURS,
    WEB_SOURCES,
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


def needs_consent(opted_in: bool, source: ConsentSource) -> bool:
    """Whether the change is a web opt-in, which identity's consent must cover."""
    return opted_in and source in WEB_SOURCES


class SetOptIn:
    """A new opt-in or opt-out replaces the address's consent. Language and quiet hours carry
    over from the previous record unless the new one gives them. ``set_for_tenant`` is kept
    only for a web source."""

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
        set_for_tenant: TenantId | None = None,
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
                set_for_tenant=set_for_tenant if source in WEB_SOURCES else None,
            )
            unit.preferences.save(preference)
        return preference


class SetPreference:
    """The preferences route's use case: ``SetOptIn`` once a web opt-in is known to be covered.

    For a web opt-in the tenant and the consent subject are required (``TenantRequiredError``,
    ``ConsentSubjectRequiredError``); the address is checked before identity is asked, a consent
    that is not recorded or not granted is ``ConsentNotRecordedError``, and an address identity
    knows is not the subject's is ``ConsentAddressNotTheirsError``. Nothing is saved unless the
    check passes, and an identity that cannot answer (``DependencyUnavailableError``) saves nothing
    either. Any other change goes straight to ``SetOptIn``; a web one keeps its tenant."""

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
            address = normalise_address(channel, recipient)
            purpose = CONSENT_PURPOSES[channel]
            answer = self._consents.check(
                tenant_id, subject, purpose, channel=channel, address=address
            )
            if not answer.granted:
                raise ConsentNotRecordedError(purpose)
            if answer.address_is_theirs is False:
                raise ConsentAddressNotTheirsError(channel.value)
        return self._set_opt_in.run(
            channel,
            recipient,
            opted_in=opted_in,
            source=source,
            language=language,
            quiet_hours=quiet_hours,
            set_for_tenant=tenant_id,
        )


class GetPreference:
    def __init__(self, unit_of_work: UnitOfWorkFactory) -> None:
        self._unit_of_work = unit_of_work

    def run(self, channel: Channel, recipient: str) -> ChannelPreference | None:
        """The address's recorded consent; None when it never opted in or out."""
        address = normalise_address(channel, recipient)
        with self._unit_of_work.shared() as unit:
            return unit.preferences.get(channel, address)
