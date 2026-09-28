"""Message templates per key, channel and language.

WhatsApp business-initiated messages must use a template Meta has approved; ``meta_name`` is
the name it will carry there and ``status`` says whether it has been submitted. Every template
here is ``draft`` until the maintainer submits it from the Meta business account (a manual
step listed in docs/runbooks/whatsapp.md). Rendering fills ``{placeholders}`` and refuses a
missing value rather than sending a message with a hole in it. Hindi copy is a first draft
for the analysts to review.
"""

import string
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from domain_kernel.channels import Channel
from domain_kernel.dedupe import DedupeKey
from domain_kernel.notifications import RenderedMessage
from notification.domain.errors import MissingPlaceholderError, UnknownTemplateError


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"


@dataclass(frozen=True, slots=True)
class MessageTemplate:
    key: str
    channel: Channel
    language: str
    body: str
    subject: str = ""
    meta_name: str = ""
    status: TemplateStatus = TemplateStatus.DRAFT

    @property
    def placeholders(self) -> tuple[str, ...]:
        names = [name for _, name, _, _ in string.Formatter().parse(self.body) if name is not None]
        return tuple(dict.fromkeys(names))


_WA = Channel.WHATSAPP
_EMAIL = Channel.EMAIL

TEMPLATES: tuple[MessageTemplate, ...] = (
    MessageTemplate(
        "obligation_due_soon",
        _WA,
        "en",
        "{business_name}: {title} is due on {due_date}. Steps: {steps}. "
        "Reply HELP for help or STOP to opt out.",
        meta_name="cw_obligation_due_soon_en",
    ),
    MessageTemplate(
        "obligation_due_soon",
        _WA,
        "hi",
        "{business_name}: {title} की अंतिम तिथि {due_date} है। चरण: {steps}। "
        "मदद के लिए HELP और बंद करने के लिए STOP लिखें।",
        meta_name="cw_obligation_due_soon_hi",
    ),
    MessageTemplate(
        "obligation_created",
        _WA,
        "en",
        "{business_name}: a new obligation applies to you. {title}, due {due_date}. "
        "Reply HELP for help or STOP to opt out.",
        meta_name="cw_obligation_created_en",
    ),
    MessageTemplate(
        "obligation_created",
        _WA,
        "hi",
        "{business_name}: आप पर एक नया दायित्व लागू होता है। {title}, अंतिम तिथि {due_date}। "
        "मदद के लिए HELP और बंद करने के लिए STOP लिखें।",
        meta_name="cw_obligation_created_hi",
    ),
    MessageTemplate(
        "opt_in_confirmed",
        _WA,
        "en",
        "You will now receive ComplianceWatch reminders on WhatsApp. Reply STOP at any time "
        "to opt out.",
    ),
    MessageTemplate(
        "opt_in_confirmed",
        _WA,
        "hi",
        "अब आपको ComplianceWatch की याद दिलाने वाली सूचनाएँ WhatsApp पर मिलेंगी। "
        "बंद करने के लिए कभी भी STOP लिखें।",
    ),
    MessageTemplate(
        "opt_out_confirmed",
        _WA,
        "en",
        "You will not receive further ComplianceWatch messages on WhatsApp. Reply START to "
        "opt in again.",
    ),
    MessageTemplate(
        "opt_out_confirmed",
        _WA,
        "hi",
        "अब आपको ComplianceWatch के संदेश WhatsApp पर नहीं मिलेंगे। फिर से शुरू करने के लिए START लिखें।",
    ),
    MessageTemplate(
        "obligation_due_soon",
        _EMAIL,
        "en",
        "{business_name}: {title} is due on {due_date}.\n\nSteps: {steps}\n\n"
        "You receive this because you enabled email reminders in ComplianceWatch.",
        subject="{title} is due on {due_date}",
    ),
)

_INDEX: Mapping[tuple[str, Channel, str], MessageTemplate] = {
    (t.key, t.channel, t.language): t for t in TEMPLATES
}


def find_template(key: str, channel: Channel, language: str) -> MessageTemplate:
    """The template in ``language``, or the English one when that language has none."""
    template = _INDEX.get((key, channel, language)) or _INDEX.get((key, channel, "en"))
    if template is None:
        raise UnknownTemplateError(key, language)
    return template


def render(
    key: str,
    channel: Channel,
    language: str,
    params: Mapping[str, object],
    *,
    recipient: str,
    dedupe_key: DedupeKey,
) -> RenderedMessage:
    template = find_template(key, channel, language)
    for name in template.placeholders:
        if name not in params:
            raise MissingPlaceholderError(key, name)
    values = {name: str(params[name]) for name in template.placeholders}
    return RenderedMessage(
        channel=channel,
        recipient=recipient,
        body=template.body.format(**values),
        dedupe_key=dedupe_key,
        subject=template.subject.format(**values) if template.subject else "",
        language=template.language,
    )
