"""Whether an address may be written to, and when: asked when a notification is queued and again
when it goes out, since consent can be withdrawn in between.

An address is open when it opted in and is not suppressed. Quiet hours are the address's own
when it set some, else the service's (``CW_QUIET_HOURS_START`` and ``CW_QUIET_HOURS_END``).
"""

from domain_kernel.channels import Channel
from notification.domain.preferences import DEFAULT_QUIET_HOURS, ChannelPreference, QuietHours
from notification.domain.recipients import AddressIsOpen, RecipientAddress
from notification.domain.repository import SharedUnitOfWork


def closed_reason(unit: SharedUnitOfWork, channel: Channel, address: str) -> str:
    """Why nothing may go to the address, or '' when it is open."""
    suppression = unit.suppressions.get(channel, address)
    if suppression is not None:
        return f"suppressed: {suppression.reason.value}"
    preference = unit.preferences.get(channel, address)
    if preference is None:
        return "not opted in"
    if not preference.opted_in:
        return "opted out"
    return ""


def open_in(unit: SharedUnitOfWork) -> AddressIsOpen:
    """The test ``Recipient.primary_address`` and ``fallback_after`` take, over ``unit``."""

    def is_open(address: RecipientAddress) -> bool:
        return not closed_reason(unit, address.channel, address.address)

    return is_open


def quiet_hours_for(preference: ChannelPreference | None, default: QuietHours) -> QuietHours:
    """The address's own quiet hours, or ``default`` when it kept the standard ones."""
    if preference is None or preference.quiet_hours == DEFAULT_QUIET_HOURS:
        return default
    return preference.quiet_hours
