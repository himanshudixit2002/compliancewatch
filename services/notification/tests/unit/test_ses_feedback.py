"""SES feedback through SNS: only a message signed with SHA-256 by a certificate on an SNS host,
from the expected topic, is read, and the SES report in it becomes one ``MailFeedback``."""

import json
from datetime import UTC, datetime
from typing import Any

import httpx2
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from domain_kernel.errors import InvariantViolationError
from notification.domain.errors import DependencyUnavailableError, EmailFeedbackInvalidError
from notification.domain.receipts import MailFeedback, ReceiptKind, SubscriptionRequest, from_ses
from notification.infrastructure.ses_feedback import (
    HttpCertificates,
    SnsFeedbackReader,
    is_sns_certificate_url,
)
from notification.testing import NOON_IST, FakeSns, ses_report

MAIL = "owner@example.com"
DISPATCH = "7b0c5f3e-1d2a-4c8b-9e6f-0a1b2c3d4e5f"
AT = datetime(2026, 9, 28, 6, 34, tzinfo=UTC)


@pytest.fixture(scope="module")
def sns() -> FakeSns:
    return FakeSns()


def reader(sns: FakeSns, **options: Any) -> SnsFeedbackReader:
    return SnsFeedbackReader(sns.certificates, clock=lambda: NOON_IST, **options)


def test_a_permanent_bounce_names_its_mailbox_and_its_dispatch(sns: FakeSns) -> None:
    body = sns.notification(ses_report("Bounce", MAIL, dispatch_id=DISPATCH))
    feedback = reader(sns, topic_arn=FakeSns.TOPIC).read(body)
    assert feedback == MailFeedback(
        kind=ReceiptKind.BOUNCED,
        at=AT,
        dispatch_id=DISPATCH,
        addresses=(MAIL,),
        detail="Permanent/General",
    )
    assert sns.fetched[-1] == FakeSns.CERT_URL


@pytest.mark.parametrize(
    ("notification_type", "bounce_type", "kind", "detail"),
    [
        ("Bounce", "Transient", ReceiptKind.FAILED, "Transient/General"),
        ("Complaint", "", ReceiptKind.COMPLAINED, "abuse"),
        ("Delivery", "", ReceiptKind.DELIVERED, ""),
    ],
)
def test_every_report_the_service_acts_on(
    sns: FakeSns, notification_type: str, bounce_type: str, kind: ReceiptKind, detail: str
) -> None:
    report = ses_report(notification_type, MAIL, bounce_type=bounce_type)
    feedback = reader(sns).read(sns.notification(report))
    assert isinstance(feedback, MailFeedback)
    assert (feedback.kind, feedback.addresses, feedback.detail) == (kind, (MAIL,), detail)
    assert feedback.dispatch_id == "", "SES left out the original headers"


def test_event_publishing_reports_and_missing_times_are_read_too(sns: FakeSns) -> None:
    report = ses_report("Complaint", MAIL)
    report["eventType"] = report.pop("notificationType")
    del report["complaint"]["timestamp"]
    feedback = reader(sns).read(sns.notification(report))
    assert isinstance(feedback, MailFeedback)
    assert feedback.at == datetime(2026, 9, 28, 6, 35, tzinfo=UTC), "the SNS time"


def test_reports_the_service_does_not_act_on_are_ignored(sns: FakeSns) -> None:
    assert reader(sns).read(sns.notification({"eventType": "Send", "mail": {}})) is None
    assert reader(sns).read(sns.confirmation("UnsubscribeConfirmation")) is None


def test_a_subscription_confirmation_is_logged_for_the_maintainer(
    sns: FakeSns, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        request = reader(sns).read(sns.confirmation())
    assert request == SubscriptionRequest(
        FakeSns.TOPIC, "https://sns.ap-south-1.amazonaws.com/?Action=ConfirmSubscription"
    )
    assert "notification.ses_subscription_pending" in caplog.text


def signed(sns: FakeSns, **changes: Any) -> str:
    envelope = json.loads(sns.notification(ses_report("Bounce", MAIL)))
    envelope.update(changes)
    return json.dumps(envelope)


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ("not json", "not JSON"),
        ("[]", "not a JSON object"),
        (json.dumps({"Type": "Notification"}), "Message is missing"),
        ("x" * (512 * 1024 + 1), "larger than any SNS message"),
    ],
)
def test_what_is_not_an_sns_message_is_refused(sns: FakeSns, body: str, reason: str) -> None:
    with pytest.raises(EmailFeedbackInvalidError, match=reason):
        reader(sns).read(body)


def test_only_a_sha256_signature_from_an_sns_certificate_verifies(sns: FakeSns) -> None:
    refused = {
        "SignatureVersion 2": signed(sns, SignatureVersion="1"),
        "not on an SNS host": signed(sns, SigningCertURL="https://evil.example/cert.pem"),
        "not base64": signed(sns, Signature="***"),
        "does not verify": signed(sns, Message=json.dumps(ses_report("Delivery", MAIL))),
    }
    for reason, body in refused.items():
        with pytest.raises(EmailFeedbackInvalidError, match=reason):
            reader(sns).read(body)


def test_another_topic_is_refused_when_the_topic_is_set(sns: FakeSns) -> None:
    body = sns.notification(ses_report("Bounce", MAIL), topic="arn:aws:sns:us-east-1:1:other")
    with pytest.raises(EmailFeedbackInvalidError, match="another topic"):
        reader(sns, topic_arn=FakeSns.TOPIC).read(body)
    assert reader(sns).read(body) is not None, "without a topic set any signed topic is read"


def test_a_certificate_out_of_its_validity_or_without_rsa_is_refused() -> None:
    expired = FakeSns(valid_until=datetime(2021, 1, 1, tzinfo=UTC))
    with pytest.raises(EmailFeedbackInvalidError, match="not valid now"):
        reader(expired).read(expired.notification(ses_report("Bounce", MAIL)))
    sns = FakeSns()
    with pytest.raises(EmailFeedbackInvalidError, match="cannot be read"):
        SnsFeedbackReader(lambda url: b"not a certificate").read(
            sns.notification(ses_report("Bounce", MAIL))
        )
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sns.amazonaws.com")])
    ec_pem = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(datetime(2020, 1, 1, tzinfo=UTC))
        .not_valid_after(datetime(2100, 1, 1, tzinfo=UTC))
        .sign(key, hashes.SHA256())
        .public_bytes(serialization.Encoding.PEM)
    )
    with pytest.raises(EmailFeedbackInvalidError, match="no RSA key"):
        SnsFeedbackReader(lambda url: ec_pem, clock=lambda: NOON_IST).read(
            sns.notification(ses_report("Bounce", MAIL))
        )


@pytest.mark.parametrize(
    ("url", "accepted"),
    [
        (FakeSns.CERT_URL, True),
        ("https://sns.us-east-1.amazonaws.com/SimpleNotificationService-abc.pem", True),
        ("http://sns.ap-south-1.amazonaws.com/cert.pem", False),
        ("https://sns.ap-south-1.amazonaws.com.evil.example/cert.pem", False),
        ("https://evil.example/sns.ap-south-1.amazonaws.com/cert.pem", False),
        ("https://user:pw@sns.ap-south-1.amazonaws.com/cert.pem", False),
        ("https://sns.ap-south-1.amazonaws.com:8443/cert.pem", False),
        ("https://sns.ap-south-1.amazonaws.com:port/cert.pem", False),
        ("https://sns.ap-south-1.amazonaws.com/cert.txt", False),
        ("https://s3.amazonaws.com/cert.pem", False),
    ],
)
def test_signing_certificates_come_only_from_sns_hosts(url: str, accepted: bool) -> None:
    assert is_sns_certificate_url(url) is accepted


def test_certificates_are_fetched_once_and_an_outage_is_a_dependency_error() -> None:
    calls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(str(request.url))
        if "missing" in str(request.url):
            return httpx2.Response(404)
        if "down" in str(request.url):
            raise httpx2.ConnectError("down")
        return httpx2.Response(200, content=b"PEM")

    certificates = HttpCertificates(httpx2.Client(transport=httpx2.MockTransport(handler)))
    assert certificates(FakeSns.CERT_URL) == certificates(FakeSns.CERT_URL) == b"PEM"
    assert calls == [FakeSns.CERT_URL]
    with pytest.raises(DependencyUnavailableError, match="HTTP 404"):
        certificates("https://sns.ap-south-1.amazonaws.com/missing.pem")
    with pytest.raises(DependencyUnavailableError, match="down"):
        certificates("https://sns.ap-south-1.amazonaws.com/down.pem")


def test_ses_types_and_bad_reports() -> None:
    assert from_ses("Bounce", "Permanent") is ReceiptKind.BOUNCED
    assert from_ses("Bounce", "Undetermined") is ReceiptKind.FAILED
    assert from_ses("Open") is None
    sns = FakeSns()
    envelope = json.loads(sns.notification(ses_report("Bounce", MAIL)))
    for message in ("not json", "[]"):
        body = json.dumps(sns.sign({**envelope, "Message": message}))
        with pytest.raises(EmailFeedbackInvalidError, match="SES report"):
            reader(sns).read(body)
    bad_time = ses_report("Bounce", MAIL, at="yesterday")
    with pytest.raises(EmailFeedbackInvalidError, match="ISO 8601"):
        reader(sns).read(sns.notification(bad_time))
    with pytest.raises(InvariantViolationError):
        MailFeedback(ReceiptKind.BOUNCED, datetime(2026, 9, 28), "", ())
