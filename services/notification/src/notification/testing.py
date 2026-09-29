"""Fakes for tests of this service and of services that send notifications."""

import base64
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from domain_kernel.channels import Channel
from domain_kernel.events import utc_now
from domain_kernel.ids import RuleVersionId
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus, RenderedMessage
from notification.domain.channels import OutboundMessage
from notification.domain.errors import DependencyUnavailableError
from notification.domain.ports import AttemptResult, QueueResult, ReceiptResult, RuleVersionFacts
from notification.domain.receipts import ReceiptKind
from notification.infrastructure.ses_feedback import DISPATCH_HEADER, signed_text
from notification.settings import NotificationSettings

BOT_TOKEN = "bot-token-for-tests"
"""A ``CW_NOTIFICATION_BOT_TOKEN`` for tests that call the receipt route."""
EMAIL_FEEDBACK_TOKEN = "email-feedback-token-for-tests"
"""A ``CW_NOTIFICATION_EMAIL_FEEDBACK_TOKEN`` for tests that post SES feedback."""
NOON_IST = datetime(2026, 9, 28, 6, 30, tzinfo=UTC)
"""12:00 IST, outside the default quiet hours."""
NIGHT_IST = datetime(2026, 9, 28, 17, 30, tzinfo=UTC)
"""23:00 IST, inside the default quiet hours."""


class FakeClock:
    """A clock the test moves: call it for the time, ``advance`` it by seconds."""

    def __init__(self, now: datetime = NOON_IST) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


class FakeChannel:
    """A channel that takes every message it could, as the real adapters decide: a WhatsApp
    message outside the 24-hour window whose template is not approved fails without a send.
    ``fail_next`` fails that many deliveries first; ``sent`` keeps the rendered messages and
    ``delivered`` the whole outbound messages."""

    def __init__(self, *, clock: Callable[[], datetime] = utc_now) -> None:
        self.sent: list[RenderedMessage] = []
        self.delivered: list[OutboundMessage] = []
        self.fail_next = 0
        self._clock = clock

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        if not message.deliverable:
            return DeliveryReceipt(
                DeliveryStatus.FAILED, self._clock(), error=message.undeliverable_reason()
            )
        if self.fail_next > 0:
            self.fail_next -= 1
            return DeliveryReceipt(DeliveryStatus.FAILED, self._clock(), error="fake: down")
        self.sent.append(message.rendered)
        self.delivered.append(message)
        return DeliveryReceipt(
            DeliveryStatus.SENT, self._clock(), provider_message_id=f"fake-{len(self.sent)}"
        )


def notification_settings(**overrides: Any) -> NotificationSettings:
    """Settings that ignore the repo ``.env``, on the memory store; the channels stay disabled
    by default."""
    values: dict[str, Any] = {
        "_env_file": None,
        "service_name": "notification",
        "notification_store": "memory",
    }
    values.update(overrides)
    return NotificationSettings(**values)


class FakeRuleVersionReader:
    """The rulebook's facts from a dict; ``down`` makes every read fail as an outage would."""

    def __init__(self, facts: Mapping[RuleVersionId, RuleVersionFacts] | None = None) -> None:
        self.facts = dict(facts or {})
        self.down = False
        self.calls: list[RuleVersionId] = []

    def get(self, rule_version_id: RuleVersionId) -> RuleVersionFacts | None:
        self.calls.append(rule_version_id)
        if self.down:
            raise DependencyUnavailableError("rulebook unreachable (fake)")
        return self.facts.get(rule_version_id)


class RecordingMetrics:
    """Keeps what the use cases count, for assertions."""

    def __init__(self) -> None:
        self.enqueues: list[tuple[Channel, QueueResult]] = []
        self.attempts: list[tuple[Channel, AttemptResult]] = []
        self.lags: list[tuple[Channel, float]] = []
        self.duplicates_sent: list[Channel] = []
        self.receipts: list[tuple[Channel, ReceiptKind, ReceiptResult]] = []

    def enqueued(self, channel: Channel, result: QueueResult) -> None:
        self.enqueues.append((channel, result))

    def attempted(self, channel: Channel, result: AttemptResult) -> None:
        self.attempts.append((channel, result))

    def delivery_lag(self, channel: Channel, seconds: float) -> None:
        self.lags.append((channel, seconds))

    def duplicate_sent(self, channel: Channel) -> None:
        self.duplicates_sent.append(channel)

    def receipt(self, channel: Channel, kind: ReceiptKind, result: ReceiptResult) -> None:
        self.receipts.append((channel, kind, result))


class FakeSns:
    """Signs SNS messages the way SNS does, with a key and a certificate of its own, and serves
    that certificate to ``SnsFeedbackReader`` (``certificates``)."""

    CERT_URL = "https://sns.ap-south-1.amazonaws.com/SimpleNotificationService-test.pem"
    TOPIC = "arn:aws:sns:ap-south-1:123456789012:cw-ses-feedback"

    def __init__(
        self,
        *,
        valid_from: datetime = datetime(2020, 1, 1, tzinfo=UTC),
        valid_until: datetime = datetime(2100, 1, 1, tzinfo=UTC),
    ) -> None:
        self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(self._key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(valid_from)
            .not_valid_after(valid_until)
            .sign(self._key, hashes.SHA256())
        )
        self.pem = certificate.public_bytes(serialization.Encoding.PEM)
        self.fetched: list[str] = []

    def certificates(self, url: str) -> bytes:
        self.fetched.append(url)
        return self.pem

    def sign(self, envelope: dict[str, Any]) -> dict[str, Any]:
        """``envelope`` with its SNS signature fields set."""
        envelope = {"SignatureVersion": "2", "SigningCertURL": self.CERT_URL, **envelope}
        signature = self._key.sign(
            signed_text(envelope).encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
        )
        envelope["Signature"] = base64.b64encode(signature).decode("ascii")
        return envelope

    def notification(self, report: Mapping[str, Any], *, topic: str = TOPIC) -> str:
        """An SNS ``Notification`` carrying the SES ``report``, signed, as SNS posts it."""
        return json.dumps(
            self.sign(
                {
                    "Type": "Notification",
                    "MessageId": str(uuid4()),
                    "TopicArn": topic,
                    "Message": json.dumps(report),
                    "Timestamp": "2026-09-28T06:35:00.000Z",
                }
            )
        )

    def confirmation(self, kind: str = "SubscriptionConfirmation") -> str:
        return json.dumps(
            self.sign(
                {
                    "Type": kind,
                    "MessageId": str(uuid4()),
                    "Token": "confirm-token",
                    "TopicArn": self.TOPIC,
                    "Message": "You have chosen to subscribe to the topic.",
                    "SubscribeURL": "https://sns.ap-south-1.amazonaws.com/?Action=ConfirmSubscription",
                    "Timestamp": "2026-09-28T06:35:00.000Z",
                }
            )
        )


def ses_report(
    notification_type: str,
    address: str,
    *,
    dispatch_id: str = "",
    bounce_type: str = "Permanent",
    at: str = "2026-09-28T06:34:00.000Z",
) -> dict[str, Any]:
    """An SES report as SES publishes it, with the original headers when ``dispatch_id`` is
    given."""
    headers = [{"name": "From", "value": "reminders@example.com"}]
    if dispatch_id:
        headers.append({"name": DISPATCH_HEADER, "value": dispatch_id})
    report: dict[str, Any] = {
        "notificationType": notification_type,
        "mail": {"timestamp": at, "messageId": "ses-message-1", "headers": headers},
    }
    if notification_type == "Bounce":
        report["bounce"] = {
            "bounceType": bounce_type,
            "bounceSubType": "General",
            "bouncedRecipients": [{"emailAddress": address}],
            "timestamp": at,
        }
    elif notification_type == "Complaint":
        report["complaint"] = {
            "complainedRecipients": [{"emailAddress": address}],
            "complaintFeedbackType": "abuse",
            "timestamp": at,
        }
    else:
        report["delivery"] = {"recipients": [address], "timestamp": at}
    return report
