"""The SMTP email channel against an smtplib stub: STARTTLS before the login, the rendered
subject and body, and the dispatch id in the X-CW-Dispatch-Id header and as the message id."""

import smtplib
import ssl
from email.message import EmailMessage
from types import TracebackType

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.notifications import DeliveryStatus
from notification.composition import EMAIL_DISABLED, default_channels
from notification.domain.channels import OutboundMessage, outbound
from notification.domain.ids import DispatchId
from notification.infrastructure.email import SmtpEmailChannel
from notification.infrastructure.whatsapp import DisabledChannel
from notification.testing import NOON_IST, notification_settings

MAIL = "owner@example.com"
SMTP_SECRET = "smtp-secret-for-tests"


def message() -> OutboundMessage:
    return outbound(
        "obligation_due_soon",
        Channel.EMAIL,
        "en",
        {"business_name": "Acme", "title": "File GSTR-3B", "due_date": "20 Oct", "steps": "File"},
        recipient=MAIL,
        dedupe_key=DedupeKey("a" * 64),
        session_open=False,
        dispatch_id=DispatchId.new(),
    )


class StubSmtp:
    """Records what the channel does on the connection; ``fail`` raises at that step."""

    def __init__(self, host: str, port: int, timeout: float, fail: str = "") -> None:
        self.opened = (host, port, timeout)
        self.steps: list[str] = []
        self.sent: list[EmailMessage] = []
        self.fail = fail

    def __enter__(self) -> "StubSmtp":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.steps.append("quit")
        if self.fail == "quit":
            raise smtplib.SMTPServerDisconnected("gone")

    def starttls(self, *, context: ssl.SSLContext) -> None:
        self.steps.append("starttls")
        if self.fail == "starttls":
            raise ConnectionResetError("reset")

    def login(self, user: str, password: str) -> None:
        self.steps.append(f"login {user} {password}")
        if self.fail == "login":
            raise smtplib.SMTPAuthenticationError(535, b"Authentication\n Credentials Invalid")

    def send_message(self, email: EmailMessage) -> None:
        self.steps.append("send")
        if self.fail == "send":
            raise smtplib.SMTPRecipientsRefused({MAIL: (550, b"no such user")})
        self.sent.append(email)


class Server:
    def __init__(self, fail: str = "") -> None:
        self.fail = fail
        self.connections: list[StubSmtp] = []

    def __call__(self, host: str, port: int, timeout: float) -> smtplib.SMTP:
        connection = StubSmtp(host, port, timeout, self.fail)
        self.connections.append(connection)
        return connection  # type: ignore[return-value]


def channel(server: Server, **options: object) -> SmtpEmailChannel:
    values: dict[str, object] = {
        "sender": "reminders@example.com",
        "username": "smtp-user",
        "password": SMTP_SECRET,
        "connect": server,
        "tls": ssl.create_default_context(),
        "clock": lambda: NOON_IST,
    }
    values.update(options)
    return SmtpEmailChannel("email-smtp.ap-south-1.amazonaws.com", 587, **values)  # type: ignore[arg-type]


def test_starttls_then_login_then_the_message_with_its_dispatch_id() -> None:
    server = Server()
    outgoing = message()
    receipt = channel(server).deliver(outgoing)
    assert receipt.status is DeliveryStatus.SENT
    assert receipt.provider_message_id == str(outgoing.dispatch_id)
    (connection,) = server.connections
    assert connection.opened == ("email-smtp.ap-south-1.amazonaws.com", 587, 20.0)
    assert connection.steps == ["starttls", f"login smtp-user {SMTP_SECRET}", "send", "quit"]
    (email,) = connection.sent
    assert (email["From"], email["To"]) == ("reminders@example.com", MAIL)
    assert email["Subject"] == "File GSTR-3B is due on 20 Oct"
    assert email["X-CW-Dispatch-Id"] == str(outgoing.dispatch_id)
    assert email["Message-ID"].endswith("@example.com>")
    assert "Acme: File GSTR-3B is due on 20 Oct." in email.get_content()


def test_without_a_username_the_channel_does_not_log_in() -> None:
    server = Server()
    channel(server, username="", password="").deliver(message())
    assert server.connections[0].steps == ["starttls", "send", "quit"]


def test_refusals_and_connection_failures_are_failed_receipts() -> None:
    expected = {
        "send": "smtp: recipient refused (550)",
        "login": "smtp: 535 Authentication Credentials Invalid",
        "starttls": "smtp: ConnectionResetError",
    }
    for step, error in expected.items():
        receipt = channel(Server(fail=step)).deliver(message())
        assert (receipt.status, receipt.error) == (DeliveryStatus.FAILED, error), step
        assert SMTP_SECRET not in receipt.error

    def refuse(host: str, port: int, timeout: float) -> smtplib.SMTP:
        raise ConnectionRefusedError("refused")

    refused = channel(Server(), connect=refuse).deliver(message())
    assert refused.error == "smtp: ConnectionRefusedError"


def test_a_failure_after_the_message_was_taken_is_still_a_send() -> None:
    receipt = channel(Server(fail="quit")).deliver(message())
    assert receipt.status is DeliveryStatus.SENT, "a retry would send it twice"


def test_the_flag_and_the_settings_wire_the_channel() -> None:
    off = default_channels(notification_settings(smtp_host="smtp.example", email_from="a@b.co"))
    assert isinstance(off[Channel.EMAIL], DisabledChannel)
    assert off[Channel.EMAIL].deliver(message()).error == EMAIL_DISABLED
    no_host = default_channels(notification_settings(email_enabled=True, email_from="a@b.co"))
    assert isinstance(no_host[Channel.EMAIL], DisabledChannel)
    on = default_channels(
        notification_settings(
            email_enabled=True,
            smtp_host="smtp.example",
            email_from="a@b.co",
            smtp_username="user",
            smtp_password=SMTP_SECRET,
        )
    )
    assert isinstance(on[Channel.EMAIL], SmtpEmailChannel)
