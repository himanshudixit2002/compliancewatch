"""A message ready for a channel, and the port every channel adapter implements.

WhatsApp lets a business write freely to a person only within 24 hours of that person's last
message to it: the customer service window (``SESSION_WINDOW``). Outside it, a business may
only send a template Meta has approved, with its parameters in order. So a message carries
both forms: the rendered text, and the template it was rendered from with its values in the
order the template names them (``ordered_params``), plus whether the window is open.

- ``OutboundMessage.deliverable`` is False for a WhatsApp message outside the window whose
  template is not approved: no attempt can deliver it until the person writes to us or Meta
  approves the template, so the dispatcher does not retry it and falls back to the recipient's
  next address at once.
- ``ChannelAdapter.deliver`` sends the message and returns the channel's receipt. The WhatsApp
  adapter sends text inside the window and the template outside it; the email adapter sends
  the rendered text. ``dispatch_id`` names the delivery, and the email adapter uses it as the
  message id that bounce reports carry back.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from domain_kernel._validation import require_aware, require_bool, require_instance
from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.notifications import DeliveryReceipt, RenderedMessage
from notification.domain.ids import DispatchId
from notification.domain.templates import (
    MessageTemplate,
    TemplateStatus,
    find_template,
    ordered_params,
    render,
)

SESSION_WINDOW = timedelta(hours=24)
"""WhatsApp's customer service window, from the person's last message to the business."""


def session_open(last_inbound_at: datetime | None, now: datetime) -> bool:
    """The person wrote to us less than 24 hours before ``now``."""
    require_aware(now, "now")
    if last_inbound_at is None:
        return False
    return now - require_aware(last_inbound_at, "last_inbound_at") < SESSION_WINDOW


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    rendered: RenderedMessage
    template: MessageTemplate
    ordered_params: tuple[str, ...]
    """The template's values in the order its body names them, for a template send."""
    session_open: bool
    """The recipient wrote to us within the last 24 hours (WhatsApp only)."""
    dispatch_id: DispatchId

    def __post_init__(self) -> None:
        require_instance(self.rendered, RenderedMessage, "rendered")
        require_instance(self.template, MessageTemplate, "template")
        object.__setattr__(self, "ordered_params", tuple(self.ordered_params))
        require_bool(self.session_open, "session_open")
        require_instance(self.dispatch_id, DispatchId, "dispatch_id")

    @property
    def channel(self) -> Channel:
        return self.rendered.channel

    @property
    def needs_template(self) -> bool:
        """Only an approved template may go: WhatsApp, outside the customer service window."""
        return self.channel is Channel.WHATSAPP and not self.session_open

    @property
    def deliverable(self) -> bool:
        """Some attempt can deliver it now: no template is needed, or the template is approved
        and has its name at Meta."""
        if not self.needs_template:
            return True
        return self.template.status is TemplateStatus.APPROVED and bool(self.template.meta_name)

    def undeliverable_reason(self) -> str:
        return (
            f"{self.channel.value}: outside the 24-hour customer service window and template "
            f"{self.template.meta_name or self.template.key} is {self.template.status.value}, "
            "not approved"
        )


def outbound(
    key: str,
    channel: Channel,
    language: str,
    values: Mapping[str, object],
    *,
    recipient: str,
    dedupe_key: DedupeKey,
    session_open: bool,
    dispatch_id: DispatchId,
) -> OutboundMessage:
    """Render ``key`` with ``values`` for ``recipient`` in both forms. An unknown template or a
    missing value raises as ``render`` does."""
    template = find_template(key, channel, language)
    rendered = render(key, channel, language, values, recipient=recipient, dedupe_key=dedupe_key)
    return OutboundMessage(
        rendered=rendered,
        template=template,
        ordered_params=ordered_params(template, values),
        session_open=session_open,
        dispatch_id=dispatch_id,
    )


class ChannelAdapter(Protocol):
    def deliver(self, message: OutboundMessage) -> DeliveryReceipt: ...
