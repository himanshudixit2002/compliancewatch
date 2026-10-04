"""The sink: a ``ChannelAdapter`` that records each message instead of sending it.

``CW_NOTIFICATION_CHANNELS=sink`` wires it for both channels (``composition.default_channels``):
the local product (``make product``) and its check run the whole chain without a Meta account or
a mail server, and nothing leaves the machine. The settings refuse it unless ``CW_ENV`` is local
or test, so a deployment never runs a channel that reaches nobody.

The delivery rules hold on the sink as they do on the real channels:

- dedupe, consent and suppressions, quiet hours, batching, digests, retries and fallbacks are the
  dispatcher's and the consumer's, decided before or after any adapter is called; the sink
  changes none of them;
- WhatsApp's 24-hour window is the adapter's to apply, and the sink applies it as the Cloud API
  adapter does (``OutboundMessage.deliverable``): a WhatsApp message outside the window whose
  template Meta has not approved is refused with the same reason, so the dispatcher falls back to
  the recipient's next channel at once;
- email takes the rendered text whatever its template's status, as the SMTP adapter does.

Draft templates: every template is a draft until Meta approves it (``domain.templates``), and the
sink handles a draft exactly as the real adapter of its channel would. So a WhatsApp message goes
through the sink only inside the window, as free text, and an email always does. A draft never
reaches a person here either way: each line names the template's status, so a recorded draft is
never mistaken for an approved message.

Each delivery appends one JSON line to ``path`` (``CW_NOTIFICATION_SINK_PATH``): when, the
outcome (``sent``, or ``refused`` with the reason), the channel, the dispatch id and the
provider message id the receipt carries (``sink:<dispatch id>``), the address, the template with
its status and language, whether the window was open, and the subject and body. The file holds
the addresses and texts the service rendered, so it stays local (``var/`` is git-ignored) and is
created readable by its owner only. The API process (``POST /send``) and the worker (the
dispatcher) may append to one file: each line goes out in one write on a descriptor opened for
appending, so lines from the two never interleave.
"""

import json
import os
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final

from domain_kernel.events import utc_now
from domain_kernel.notifications import DeliveryReceipt, DeliveryStatus
from notification.domain.channels import OutboundMessage
from py_common.logging import get_logger

MESSAGE_ID_PREFIX: Final = "sink:"
"""What a provider message id the sink gives starts with."""
FILE_MODE: Final = 0o600
"""Owner read and write: the lines carry addresses."""
SENT: Final = "sent"
REFUSED: Final = "refused"

log = get_logger(__name__)


class SinkChannel:
    def __init__(self, path: Path, *, clock: Callable[[], datetime] = utc_now) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def deliver(self, message: OutboundMessage) -> DeliveryReceipt:
        at = self._clock()
        if not message.deliverable:
            reason = message.undeliverable_reason()
            self._record(message, at, REFUSED, error=reason)
            return DeliveryReceipt(DeliveryStatus.FAILED, at, error=reason)
        message_id = MESSAGE_ID_PREFIX + str(message.dispatch_id)
        if not self._record(message, at, SENT, message_id=message_id):
            return DeliveryReceipt(
                DeliveryStatus.FAILED, at, error="sink: the message could not be recorded"
            )
        return DeliveryReceipt(DeliveryStatus.SENT, at, provider_message_id=message_id)

    def _record(
        self,
        message: OutboundMessage,
        at: datetime,
        outcome: str,
        *,
        message_id: str = "",
        error: str = "",
    ) -> bool:
        """Append the message's line; False when the file cannot take it."""
        rendered = message.rendered
        line = json.dumps(
            {
                "at": at.isoformat(),
                "outcome": outcome,
                "channel": message.channel.value,
                "dispatch_id": str(message.dispatch_id),
                "provider_message_id": message_id,
                "error": error,
                "recipient": rendered.recipient,
                "template": message.template.key,
                "template_status": message.template.status.value,
                "language": rendered.language,
                "session_open": message.session_open,
                "subject": rendered.subject,
                "body": rendered.body,
            },
            ensure_ascii=False,
        )
        data = (line + "\n").encode("utf-8")
        try:
            with self._lock:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, FILE_MODE)
                try:
                    os.write(descriptor, data)
                finally:
                    os.close(descriptor)
        except OSError as exc:
            log.error(
                "notification.sink_unwritable", path=str(self._path), error=type(exc).__name__
            )
            return False
        return True
