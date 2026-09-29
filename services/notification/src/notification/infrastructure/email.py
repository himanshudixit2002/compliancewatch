"""Email over SMTP as a ``ChannelAdapter``: the Amazon SES SMTP interface in production, any
SMTP server with STARTTLS locally.

Each message is one plain-text email from ``CW_EMAIL_FROM`` to the recipient, with the rendered
subject and body. The connection is upgraded with STARTTLS (the server's certificate is checked)
before the credentials go over it, and the channel logs in when a username is set. SMTP returns
no message id SES reports back, so the message carries its dispatch id in the
``X-CW-Dispatch-Id`` header and the receipt names the dispatch id as the provider's message id:
SES includes that header in its bounce and complaint reports when the configuration set is told
to (a manual step), which is how a report finds its notifications. A refused recipient, a
refused login or a connection that fails is a failed receipt, and the dispatcher retries it.

The channel is wired only behind ``CW_EMAIL_ENABLED`` with ``CW_SMTP_HOST`` and
``CW_EMAIL_FROM``; otherwise the composition root wires ``DisabledChannel``.
"""

import smtplib
import ssl
from collections.abc import Callable
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from domain_kernel.events import utc_now
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus
from notification.domain.channels import OutboundMessage
from notification.infrastructure.ses_feedback import DISPATCH_HEADER

DEFAULT_TIMEOUT_SECONDS = 20.0
"""Shorter than the dispatcher's 60-second lease, so a hung server cannot outlast it."""

SmtpFactory = Callable[[str, int, float], smtplib.SMTP]
"""Opens a connection: host, port and timeout in seconds."""


def _connect(host: str, port: int, timeout: float) -> smtplib.SMTP:
    return smtplib.SMTP(host, port, timeout=timeout)


class SmtpEmailChannel:
    def __init__(
        self,
        host: str,
        port: int = 587,
        *,
        sender: str,
        username: str = "",
        password: str = "",
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        connect: SmtpFactory = _connect,
        tls: ssl.SSLContext | None = None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._timeout = timeout
        self._connect = connect
        self._tls = tls
        self._clock = clock

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        rendered = message.rendered
        email = EmailMessage()
        email["From"] = self._sender
        email["To"] = rendered.recipient
        email["Subject"] = rendered.subject
        email["Date"] = formatdate(usegmt=True)
        email["Message-ID"] = make_msgid(domain=self._sender.rpartition("@")[2] or None)
        email[DISPATCH_HEADER] = str(message.dispatch_id)
        email["Content-Language"] = rendered.language
        email.set_content(rendered.body)
        sent = False
        try:
            with self._connect(self._host, self._port, self._timeout) as smtp:
                smtp.starttls(context=self._tls or ssl.create_default_context())
                if self._username:
                    smtp.login(self._username, self._password)
                smtp.send_message(email)
                sent = True
        except (smtplib.SMTPException, OSError) as exc:
            # A failure while closing a connection that already took the message is no failure
            # of the message: retrying it would send it twice.
            if not sent:
                return DeliveryReceipt(
                    DeliveryStatus.FAILED, self._clock(), error=f"smtp: {_describe(exc)}"
                )
        return DeliveryReceipt(
            DeliveryStatus.SENT, self._clock(), provider_message_id=str(message.dispatch_id)
        )


def _describe(exc: Exception) -> str:
    """The SMTP code and reply of a refusal, or the kind of connection failure; never the
    message or the credentials."""
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        codes = sorted({code for code, _ in exc.recipients.values()})
        return f"recipient refused ({', '.join(str(code) for code in codes)})"
    if isinstance(exc, smtplib.SMTPResponseException):
        error = exc.smtp_error
        reply = error.decode("utf-8", "replace") if isinstance(error, bytes) else str(error)
        return f"{exc.smtp_code} {' '.join(reply.split())}"[:300]
    return type(exc).__name__
