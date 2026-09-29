"""One key per address, whoever typed it.

The bot sees a WhatsApp number as Meta sends it (``919876543210``), the web app as the person
typed it (``+91 98765 43210``). Preferences, suppressions, recipients and the address directory
are keyed by the normalised form, so both reach the same consent and the same person.

- WhatsApp: the digits with a leading ``+``, 8 to 15 of them, the first not zero (E.164).
  Spaces, dashes, dots and parentheses are dropped, and a leading ``00`` counts as ``+``. No
  country code is guessed: a number without one stays as it is and is a different key.
- Email: trimmed and lower-cased, one ``@``, a local part of at most 64 characters without
  leading, trailing or doubled dots, and a domain of at least two labels.

Anything else raises ``InvalidAddressError``, whose detail never repeats the address.
"""

import re

from domain_kernel.channels import Channel
from notification.domain.errors import InvalidAddressError

_PHONE_NOISE = re.compile(r"[\s\-.()]")
_PHONE_DIGITS = re.compile(r"[1-9][0-9]{7,14}")
_EMAIL_LOCAL = re.compile(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+")
_EMAIL_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
MAX_EMAIL_LENGTH = 254
MAX_LOCAL_LENGTH = 64


def normalise_address(channel: Channel, raw: str) -> str:
    """The address as the stores key it; ``InvalidAddressError`` when it cannot be one."""
    if channel is Channel.WHATSAPP:
        return _phone(raw)
    return _email(raw)


def _phone(raw: str) -> str:
    text = _PHONE_NOISE.sub("", raw.strip())
    if text.startswith("+"):
        text = text[1:]
    elif text.startswith("00"):
        text = text[2:]
    if not _PHONE_DIGITS.fullmatch(text):
        raise InvalidAddressError(
            Channel.WHATSAPP.value,
            "expected a phone number with its country code, 8 to 15 digits",
        )
    return "+" + text


def _email(raw: str) -> str:
    text = raw.strip().lower()
    reason = _email_problem(text)
    if reason:
        raise InvalidAddressError(Channel.EMAIL.value, reason)
    return text


def _email_problem(text: str) -> str:
    """Why ``text`` is not an email address, or '' when it is one."""
    if len(text) > MAX_EMAIL_LENGTH:
        return f"longer than {MAX_EMAIL_LENGTH} characters"
    local, at, domain = text.rpartition("@")
    if not at or not local or "@" in local:
        return "expected exactly one @ between a local part and a domain"
    if len(local) > MAX_LOCAL_LENGTH or not _EMAIL_LOCAL.fullmatch(local):
        return "the local part has characters an address cannot carry"
    if local.startswith(".") or local.endswith(".") or ".." in local:
        return "the local part has a leading, trailing or doubled dot"
    labels = domain.split(".")
    if len(labels) < 2 or not all(_EMAIL_LABEL.fullmatch(label) for label in labels):
        return "expected a domain of at least two labels, such as example.com"
    return ""
