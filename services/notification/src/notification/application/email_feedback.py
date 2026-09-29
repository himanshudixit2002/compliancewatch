"""Email feedback: what Amazon SES reports, through SNS, after it took a message.

``ReceiveEmailFeedback.run(body)`` hands the SNS message to the ``EmailFeedbackReader``, which
verifies its signature and reads the SES report (``infrastructure.ses_feedback``), and then:

- a delivery marks the message's notifications delivered;
- a bounce or a complaint fails the ones still only sent (``notification.failed``, and the
  fallback on the recipient's next address, as for any failure after sending). A permanent
  bounce and a complaint also suppress every mailbox the report names, for every tenant, even
  when the message cannot be matched because SES left out its original headers;
- a subscription confirmation is left to the maintainer, who opens the URL the reader logged.

The message is matched by its ``X-CW-Dispatch-Id`` header: the email channel sends the dispatch
id as the provider message id, and the work index finds the tenant by it.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from domain_kernel.channels import Channel
from notification.application.receipts import ClosedAddress, Reconciled, ReconcileReceipts
from notification.domain.ports import EmailFeedbackReader
from notification.domain.preferences import SuppressionReason
from notification.domain.receipts import FAILURE_KINDS, Receipt, ReceiptKind, SubscriptionRequest

SUPPRESSED_BY = {
    ReceiptKind.BOUNCED: SuppressionReason.BOUNCE,
    ReceiptKind.COMPLAINED: SuppressionReason.COMPLAINT,
}
"""The reports that close a mailbox for good, and the reason each records."""


class FeedbackKind(StrEnum):
    REPORT = "report"
    """An SES delivery, bounce or complaint."""
    SUBSCRIPTION_CONFIRMATION = "subscription_confirmation"
    IGNORED = "ignored"
    """A verified message the service does not act on."""


@dataclass(frozen=True, slots=True)
class FeedbackOutcome:
    kind: FeedbackKind
    reconciled: Reconciled = field(default_factory=Reconciled)


class ReceiveEmailFeedback:
    def __init__(self, reader: EmailFeedbackReader, reconcile: ReconcileReceipts) -> None:
        self._reader = reader
        self._reconcile = reconcile

    def run(self, body: str) -> FeedbackOutcome:
        feedback = self._reader.read(body)
        if isinstance(feedback, SubscriptionRequest):
            return FeedbackOutcome(FeedbackKind.SUBSCRIPTION_CONFIRMATION)
        if feedback is None:
            return FeedbackOutcome(FeedbackKind.IGNORED)
        receipts = []
        if feedback.dispatch_id:
            error = ""
            if feedback.kind in FAILURE_KINDS:
                error = f"email {feedback.kind.value}: {feedback.detail or 'no detail'}"
            receipts.append(Receipt(feedback.dispatch_id, feedback.kind, feedback.at, error=error))
        reason = SUPPRESSED_BY.get(feedback.kind)
        closed = (
            []
            if reason is None
            else [
                ClosedAddress(address, reason, feedback.at, feedback.detail)
                for address in feedback.addresses
            ]
        )
        reconciled = self._reconcile.run(Channel.EMAIL, receipts, closed=closed)
        return FeedbackOutcome(FeedbackKind.REPORT, reconciled)
