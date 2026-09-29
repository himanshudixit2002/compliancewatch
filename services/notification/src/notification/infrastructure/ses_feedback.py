"""Amazon SES feedback through SNS: verify the SNS message, then read the SES report in it.

SES publishes the bounces, complaints and deliveries of the sending configuration set to an SNS
topic, and SNS posts each to ``POST /v1/notification/receipts/email`` as JSON in a text/plain
body. Nothing in it is believed before the message is verified:

- ``SignatureVersion`` must be ``2`` (RSA with SHA-256); version 1 (SHA-1) is refused.
- ``SigningCertURL`` must be an https URL on ``sns.<region>.amazonaws.com`` naming a ``.pem``
  file. The certificate is fetched from there (and kept), must be within its validity, and the
  signature must verify over the text SNS signs: the message's fields in SNS's order, each as
  its name and value on lines of their own.
- With ``CW_NOTIFICATION_SES_TOPIC_ARN`` set, the message must come from that topic, since a
  valid signature proves only that SNS sent it, not that the service's topic did.

A ``SubscriptionConfirmation`` is logged once with its ``SubscribeURL``, which the maintainer
opens by hand to confirm the subscription (docs/runbooks/notification-delivery.md). A
``Notification`` carries the SES report as JSON in ``Message``: its type (``notificationType``,
or ``eventType`` when a configuration set publishes events), the mailboxes it names, and, when
the configuration set includes the original headers, the message's ``X-CW-Dispatch-Id`` header,
by which the service finds its notifications.
"""

import base64
import binascii
import json
import re
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx2
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from domain_kernel.events import utc_now
from notification.domain.errors import DependencyUnavailableError, EmailFeedbackInvalidError
from notification.domain.receipts import MailFeedback, SubscriptionRequest, from_ses
from py_common.logging import get_logger

log = get_logger(__name__)

DISPATCH_HEADER = "X-CW-Dispatch-Id"
SIGNATURE_VERSION = "2"
MAX_BODY_BYTES = 512 * 1024
"""Twice the largest message SNS delivers."""
SNS_HOST = re.compile(r"sns\.[a-z0-9-]+\.amazonaws\.com")
NOTIFICATION_FIELDS = ("Message", "MessageId", "Subject", "Timestamp", "TopicArn", "Type")
CONFIRMATION_FIELDS = (
    "Message",
    "MessageId",
    "SubscribeURL",
    "Timestamp",
    "Token",
    "TopicArn",
    "Type",
)
"""The fields SNS signs, in the order it signs them; ``Subject`` only when the message has one."""
CONFIRMATION_TYPES = frozenset({"SubscriptionConfirmation", "UnsubscribeConfirmation"})

CertificateFetcher = Callable[[str], bytes]
"""The PEM bytes at a signing certificate URL."""


class HttpCertificates:
    """Fetches signing certificates over HTTPS and keeps each, since SNS signs with few."""

    def __init__(self, client: httpx2.Client | None = None) -> None:
        self._client = client or httpx2.Client(timeout=10.0)
        self._known: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def __call__(self, url: str) -> bytes:
        with self._lock:
            known = self._known.get(url)
        if known is not None:
            return known
        try:
            response = self._client.get(url)
        except httpx2.TransportError as exc:
            raise DependencyUnavailableError(f"SNS signing certificate: {exc}") from exc
        if response.status_code != 200:
            raise DependencyUnavailableError(
                f"SNS signing certificate: HTTP {response.status_code}"
            )
        with self._lock:
            self._known[url] = response.content
        return response.content


class SnsFeedbackReader:
    def __init__(
        self,
        certificates: CertificateFetcher | None = None,
        *,
        topic_arn: str = "",
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._certificates = certificates or HttpCertificates()
        self._topic_arn = topic_arn
        self._clock = clock

    def read(self, body: str) -> MailFeedback | SubscriptionRequest | None:
        envelope = _envelope(body)
        kind = _text(envelope, "Type")
        if self._topic_arn and _text(envelope, "TopicArn") != self._topic_arn:
            raise EmailFeedbackInvalidError("the message is from another topic")
        self._verify(envelope)
        if kind == "SubscriptionConfirmation":
            request = SubscriptionRequest(
                _text(envelope, "TopicArn"), _text(envelope, "SubscribeURL")
            )
            log.warning(
                "notification.ses_subscription_pending",
                topic_arn=request.topic_arn,
                subscribe_url=request.confirm_url,
            )
            return request
        if kind != "Notification":
            log.info("notification.ses_message_ignored", sns_type=kind)
            return None
        return _feedback(_text(envelope, "Message"), _text(envelope, "Timestamp"))

    def _verify(self, envelope: Mapping[str, Any]) -> None:
        if envelope.get("SignatureVersion") != SIGNATURE_VERSION:
            raise EmailFeedbackInvalidError("only SignatureVersion 2 (SHA-256) is accepted")
        url = _text(envelope, "SigningCertURL")
        if not is_sns_certificate_url(url):
            raise EmailFeedbackInvalidError("the signing certificate is not on an SNS host")
        try:
            signature = base64.b64decode(_text(envelope, "Signature"), validate=True)
        except binascii.Error as exc:
            raise EmailFeedbackInvalidError("the signature is not base64") from exc
        try:
            certificate = x509.load_pem_x509_certificate(self._certificates(url))
        except ValueError as exc:
            raise EmailFeedbackInvalidError("the signing certificate cannot be read") from exc
        now = self._clock()
        if not certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc:
            raise EmailFeedbackInvalidError("the signing certificate is not valid now")
        key = certificate.public_key()
        if not isinstance(key, rsa.RSAPublicKey):
            raise EmailFeedbackInvalidError("the signing certificate has no RSA key")
        try:
            key.verify(
                signature,
                signed_text(envelope).encode("utf-8"),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except InvalidSignature as exc:
            raise EmailFeedbackInvalidError("the signature does not verify") from exc


def is_sns_certificate_url(url: str) -> bool:
    """An https URL on ``sns.<region>.amazonaws.com``, no port or credentials, naming a .pem."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "https"
        and parts.username is None
        and port is None
        and SNS_HOST.fullmatch(parts.hostname or "") is not None
        and parts.path.endswith(".pem")
    )


def signed_text(envelope: Mapping[str, Any]) -> str:
    """The text SNS signs for the message: each signed field it has, name and value on lines of
    their own, in SNS's order."""
    fields = (
        CONFIRMATION_FIELDS if envelope.get("Type") in CONFIRMATION_TYPES else NOTIFICATION_FIELDS
    )
    lines: list[str] = []
    for name in fields:
        value = envelope.get(name)
        if value is None and name == "Subject":
            continue
        lines.extend((name, str(value)))
    return "\n".join(lines) + "\n"


def _envelope(body: str) -> Mapping[str, Any]:
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise EmailFeedbackInvalidError("the body is larger than any SNS message")
    try:
        envelope = json.loads(body)
    except ValueError as exc:
        raise EmailFeedbackInvalidError("the body is not JSON") from exc
    if not isinstance(envelope, dict):
        raise EmailFeedbackInvalidError("the body is not a JSON object")
    fields = (
        CONFIRMATION_FIELDS if envelope.get("Type") in CONFIRMATION_TYPES else NOTIFICATION_FIELDS
    )
    for name in (*fields, "Signature", "SigningCertURL", "SignatureVersion"):
        if name != "Subject":
            _text(envelope, name)
    return envelope


def _text(envelope: Mapping[str, Any], name: str) -> str:
    value = envelope.get(name)
    if not isinstance(value, str) or not value:
        raise EmailFeedbackInvalidError(f"{name} is missing")
    return value


def _feedback(message: str, sent_at: str) -> MailFeedback | None:
    """The SES report in a notification's ``Message``; None for a type the service ignores."""
    try:
        report = json.loads(message)
    except ValueError as exc:
        raise EmailFeedbackInvalidError("the SES report is not JSON") from exc
    if not isinstance(report, dict):
        raise EmailFeedbackInvalidError("the SES report is not a JSON object")
    ses_type = str(report.get("notificationType") or report.get("eventType") or "")
    bounce = _object(report, "bounce")
    kind = from_ses(ses_type, str(bounce.get("bounceType", "")))
    if kind is None:
        log.info("notification.ses_report_ignored", ses_type=ses_type)
        return None
    detail = ""
    if ses_type == "Bounce":
        addresses = _mailboxes(bounce.get("bouncedRecipients"))
        detail = "/".join(
            str(bounce[name]) for name in ("bounceType", "bounceSubType") if bounce.get(name)
        )
        at = bounce.get("timestamp")
    elif ses_type == "Complaint":
        complaint = _object(report, "complaint")
        addresses = _mailboxes(complaint.get("complainedRecipients"))
        detail = str(complaint.get("complaintFeedbackType") or "complaint")
        at = complaint.get("timestamp")
    else:
        delivery = _object(report, "delivery")
        recipients = delivery.get("recipients")
        addresses = tuple(str(item) for item in recipients) if isinstance(recipients, list) else ()
        at = delivery.get("timestamp")
    return MailFeedback(
        kind=kind,
        at=_moment(at if isinstance(at, str) else sent_at),
        dispatch_id=_dispatch_id(_object(report, "mail")),
        addresses=addresses,
        detail=detail,
    )


def _object(report: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = report.get(name)
    return value if isinstance(value, dict) else {}


def _mailboxes(recipients: object) -> tuple[str, ...]:
    if not isinstance(recipients, list):
        return ()
    return tuple(
        str(item["emailAddress"])
        for item in recipients
        if isinstance(item, dict) and item.get("emailAddress")
    )


def _dispatch_id(mail: Mapping[str, Any]) -> str:
    headers = mail.get("headers")
    if not isinstance(headers, list):
        return ""
    for header in headers:
        if (
            isinstance(header, dict)
            and str(header.get("name", "")).lower() == DISPATCH_HEADER.lower()
        ):
            return str(header.get("value", "")).strip()
    return ""


def _moment(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EmailFeedbackInvalidError("a timestamp is not ISO 8601") from exc
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
