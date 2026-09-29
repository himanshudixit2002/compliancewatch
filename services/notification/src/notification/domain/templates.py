"""Message templates per key, channel and language.

WhatsApp business-initiated messages must use a template Meta has approved; ``meta_name`` is
the name it will carry there and ``status`` says whether it has been submitted. Every template
here is ``draft`` until the maintainer submits it from the Meta business account (a manual
step listed in docs/runbooks/whatsapp.md). Rendering fills ``{placeholders}`` and refuses a
missing value rather than sending a message with a hole in it. Hindi copy is a first draft
for the analysts to review.

The templates of the notifications the service sends on its own, each as WhatsApp in English
and Hindi and as email in English:

- ``change_card``: a rule now applies to the business. What changed, that it applies, from
  when, what to do and by when; the facts come from the rulebook's published rule version.
- ``obligation_closed``: an obligation was closed because the business profile changed or a
  newer rule version replaced it. A withdrawn rule has ``obligation_withdrawn`` instead.
- ``batch_summary``: several notifications for one business in one message, such as the
  closures and creations a profile change makes.
- ``daily_digest`` and ``ca_digest``: the day's notifications of a person who asked for a
  digest, and of a CA firm's people across their clients.
- The three outcomes of a deadline change (ADR-015): ``obligation_deadline_extended``,
  ``obligation_corrected`` (a corrected due date) and ``obligation_withdrawn``.

The copy holds placeholders only: every regulatory fact in a message (a title, a summary, a
date, a step, a source) comes from the rulebook or the obligation, never from this module.
Summary and digest lines, and the short phrases a message fills in when a value is missing
(``phrase``), are copy as well and live here.

WhatsApp template sends carry the values as an ordered list (``ordered_params``). Meta refuses
a parameter with a newline, a tab or more than four spaces in a row, so the values of a
WhatsApp template are flattened to one line (``one_line``).

``CHANGE_TEMPLATES`` names the template for each deadline change a customer is told about:
extended, corrected or withdrawn (ADR-015). ``template_for_change`` looks it up.
"""

import string
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

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

DUE_SOON = "obligation_due_soon"
CREATED = "obligation_created"
DEADLINE_EXTENDED = "obligation_deadline_extended"
CORRECTED = "obligation_corrected"
WITHDRAWN = "obligation_withdrawn"
CHANGE_CARD = "change_card"
CLOSED = "obligation_closed"
BATCH_SUMMARY = "batch_summary"
DAILY_DIGEST = "daily_digest"
CA_DIGEST = "ca_digest"

_HELP_EN = "Reply HELP for help or STOP to opt out."
_HELP_HI = "मदद के लिए HELP और बंद करने के लिए STOP लिखें।"
_EMAIL_FOOTER = "You receive this because you enabled email reminders in ComplianceWatch."

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
        "obligation_created",
        _EMAIL,
        "en",
        "{business_name}: a new obligation applies to you. {title}, due {due_date}.\n\n"
        + _EMAIL_FOOTER,
        subject="New obligation: {title}",
    ),
    MessageTemplate(
        "obligation_due_soon",
        _EMAIL,
        "en",
        "{business_name}: {title} is due on {due_date}.\n\nSteps: {steps}\n\n"
        "You receive this because you enabled email reminders in ComplianceWatch.",
        subject="{title} is due on {due_date}",
    ),
    # The three outcomes of a deadline change (ADR-015). Each opens with what changed;
    # source_ref names what the regulator published, as the rulebook cites it. The withdrawn
    # template has no dates: there is no longer a due date to give.
    MessageTemplate(
        DEADLINE_EXTENDED,
        _WA,
        "en",
        "Due date extended for {business_name}: {title} was due on {previous_due_date} and is "
        "now due on {new_due_date}. Source: {source_ref}. Reply HELP for help or STOP to opt out.",
        meta_name="cw_obligation_deadline_extended_en",
    ),
    MessageTemplate(
        DEADLINE_EXTENDED,
        _WA,
        "hi",
        "सूचना: {business_name} के लिए {title} की अंतिम तिथि {previous_due_date} से बढ़ाकर "
        "{new_due_date} कर दी गई है। स्रोत: {source_ref}। "
        "मदद के लिए HELP और बंद करने के लिए STOP लिखें।",
        meta_name="cw_obligation_deadline_extended_hi",
    ),
    MessageTemplate(
        DEADLINE_EXTENDED,
        _EMAIL,
        "en",
        "Due date extended for {business_name}: {title} was due on {previous_due_date} and is "
        "now due on {new_due_date}.\n\nSource: {source_ref}\n\n"
        "You receive this because you enabled email reminders in ComplianceWatch.",
        subject="Due date extended: {title} is now due on {new_due_date}",
    ),
    MessageTemplate(
        CORRECTED,
        _WA,
        "en",
        "Due date corrected for {business_name}: {title} is due on {new_due_date}, not "
        "{previous_due_date}. Source: {source_ref}. Reply HELP for help or STOP to opt out.",
        meta_name="cw_obligation_corrected_en",
    ),
    MessageTemplate(
        CORRECTED,
        _WA,
        "hi",
        "सुधार: {business_name} के लिए {title} की अंतिम तिथि {new_due_date} है, "
        "{previous_due_date} नहीं। स्रोत: {source_ref}। "
        "मदद के लिए HELP और बंद करने के लिए STOP लिखें।",
        meta_name="cw_obligation_corrected_hi",
    ),
    MessageTemplate(
        CORRECTED,
        _EMAIL,
        "en",
        "Due date corrected for {business_name}: {title} is due on {new_due_date}, not "
        "{previous_due_date}.\n\nSource: {source_ref}\n\n"
        "You receive this because you enabled email reminders in ComplianceWatch.",
        subject="Due date corrected: {title} is due on {new_due_date}",
    ),
    MessageTemplate(
        WITHDRAWN,
        _WA,
        "en",
        "Update for {business_name}: {title} no longer applies because the rule behind it was "
        "withdrawn. Source: {source_ref}. Reply HELP for help or STOP to opt out.",
        meta_name="cw_obligation_withdrawn_en",
    ),
    MessageTemplate(
        WITHDRAWN,
        _WA,
        "hi",
        "सूचना: {business_name} के लिए {title} अब लागू नहीं है, क्योंकि इसका नियम वापस ले लिया "
        "गया है। स्रोत: {source_ref}। मदद के लिए HELP और बंद करने के लिए STOP लिखें।",
        meta_name="cw_obligation_withdrawn_hi",
    ),
    MessageTemplate(
        WITHDRAWN,
        _EMAIL,
        "en",
        "Update for {business_name}: {title} no longer applies because the rule behind it was "
        "withdrawn.\n\nSource: {source_ref}\n\n"
        "You receive this because you enabled email reminders in ComplianceWatch.",
        subject="No longer applies: {title}",
    ),
    # A rule now applies to the business: what changed, that it applies, from when, what to do
    # and by when. The summary, dates and steps are the rule version's and the obligation's.
    MessageTemplate(
        CHANGE_CARD,
        _WA,
        "en",
        "What changed for {business_name}: {summary}. It applies to you from {applies_from}. "
        "What to do: {steps}. Due date: {due_date}. Open {link} for details. " + _HELP_EN,
        meta_name="cw_change_card_en",
    ),
    MessageTemplate(
        CHANGE_CARD,
        _WA,
        "hi",
        "सूचना: {business_name} के लिए क्या बदला: {summary}। यह आप पर {applies_from} से लागू है। "
        "क्या करें: {steps}। अंतिम तिथि: {due_date}। विवरण के लिए {link} खोलें। " + _HELP_HI,
        meta_name="cw_change_card_hi",
    ),
    MessageTemplate(
        CHANGE_CARD,
        _EMAIL,
        "en",
        "What changed for {business_name}: {summary}.\n\nIt applies to you from {applies_from}."
        "\n\nWhat to do: {steps}\n\nDue date: {due_date}\n\nDetails: {link}\n\n" + _EMAIL_FOOTER,
        subject="What changed for {business_name}: applies from {applies_from}",
    ),
    MessageTemplate(
        CLOSED,
        _WA,
        "en",
        "Update for {business_name}: {title} was closed on {closed_on} because {reason}. It no "
        "longer appears in your compliance calendar. " + _HELP_EN,
        meta_name="cw_obligation_closed_en",
    ),
    MessageTemplate(
        CLOSED,
        _WA,
        "hi",
        "सूचना: {business_name} के लिए {title} {closed_on} को बंद किया गया, क्योंकि {reason}। "
        "यह अब आपके अनुपालन कैलेंडर में नहीं है। " + _HELP_HI,
        meta_name="cw_obligation_closed_hi",
    ),
    MessageTemplate(
        CLOSED,
        _EMAIL,
        "en",
        "Update for {business_name}: {title} was closed on {closed_on} because {reason}.\n\n"
        "It no longer appears in your compliance calendar.\n\n" + _EMAIL_FOOTER,
        subject="Closed: {title}",
    ),
    # Several notifications as one message. ``lines`` is the list ``digest.compose`` builds:
    # one short line per notification, '; ' between them on WhatsApp and a newline in email.
    MessageTemplate(
        BATCH_SUMMARY,
        _WA,
        "en",
        "Updates for {business_name}. Changes to your compliance calendar: {count}. {lines}. "
        "Open {link} for details. " + _HELP_EN,
        meta_name="cw_batch_summary_en",
    ),
    MessageTemplate(
        BATCH_SUMMARY,
        _WA,
        "hi",
        "सूचना: {business_name} के अनुपालन कैलेंडर में बदलाव: {count}। {lines}। "
        "विवरण के लिए {link} खोलें। " + _HELP_HI,
        meta_name="cw_batch_summary_hi",
    ),
    MessageTemplate(
        BATCH_SUMMARY,
        _EMAIL,
        "en",
        "Updates for {business_name}. Changes to your compliance calendar: {count}.\n\n{lines}"
        "\n\nDetails: {link}\n\n" + _EMAIL_FOOTER,
        subject="Compliance calendar updates for {business_name}",
    ),
    MessageTemplate(
        DAILY_DIGEST,
        _WA,
        "en",
        "Your ComplianceWatch digest for today. Updates: {count}. {lines}. "
        "Open {link} for details. " + _HELP_EN,
        meta_name="cw_daily_digest_en",
    ),
    MessageTemplate(
        DAILY_DIGEST,
        _WA,
        "hi",
        "आज का ComplianceWatch सारांश। अपडेट: {count}। {lines}। विवरण के लिए {link} खोलें। " + _HELP_HI,
        meta_name="cw_daily_digest_hi",
    ),
    MessageTemplate(
        DAILY_DIGEST,
        _EMAIL,
        "en",
        "Your ComplianceWatch digest for today. Updates: {count}.\n\n{lines}\n\n"
        "Details: {link}\n\n" + _EMAIL_FOOTER,
        subject="Your ComplianceWatch digest for today",
    ),
    MessageTemplate(
        CA_DIGEST,
        _WA,
        "en",
        "Client digest for {org_label}. Updates: {count}. Clients: {client_count}. {lines}. "
        "Open {link} for details. " + _HELP_EN,
        meta_name="cw_ca_digest_en",
    ),
    MessageTemplate(
        CA_DIGEST,
        _WA,
        "hi",
        "क्लाइंट सारांश, {org_label}। अपडेट: {count}। क्लाइंट: {client_count}। {lines}। "
        "विवरण के लिए {link} खोलें। " + _HELP_HI,
        meta_name="cw_ca_digest_hi",
    ),
    MessageTemplate(
        CA_DIGEST,
        _EMAIL,
        "en",
        "Client digest for {org_label}. Updates: {count}. Clients: {client_count}.\n\n{lines}"
        "\n\nDetails: {link}\n\n" + _EMAIL_FOOTER,
        subject="Client digest for {org_label}",
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
        # A subject is one mail header line, which refuses a line break: a value typed over two
        # lines (a business label, a title) is flattened into it.
        subject=one_line(template.subject.format(**values)) if template.subject else "",
        language=template.language,
    )


CHANGE_TEMPLATES: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        ("obligation.rescheduled", "deadline_extended"): DEADLINE_EXTENDED,
        ("obligation.rescheduled", "corrected"): CORRECTED,
        ("obligation.closed", "rule_withdrawn"): WITHDRAWN,
    }
)
"""The template of each deadline change the customer hears about, by the obligation event's
topic and reason (ADR-015). The notification routing table reuses it."""

SILENT_CHANGES: frozenset[tuple[str, str]] = frozenset({("obligation.rescheduled", "manual")})
"""Changes that send no customer message: a manual reschedule."""


def template_for_change(topic: str, reason: str) -> str | None:
    """The template key for a deadline change, or None for a change that sends no message.

    A (topic, reason) pair that is neither mapped nor silent raises ``UnknownTemplateError``
    rather than dropping the change without a word.
    """
    key = CHANGE_TEMPLATES.get((topic, reason))
    if key is None and (topic, reason) not in SILENT_CHANGES:
        raise UnknownTemplateError(f"{topic} with reason {reason}")
    return key


def one_line(value: object) -> str:
    """``value`` as text on one line: newlines, tabs and runs of spaces become one space, as a
    WhatsApp template parameter must be."""
    return " ".join(str(value).split())


def ordered_params(template: MessageTemplate, params: Mapping[str, object]) -> tuple[str, ...]:
    """The values of ``template``'s placeholders in the order its body names them, as a Meta
    template send lists its parameters. A WhatsApp template's values are flattened to one line;
    a missing value raises ``MissingPlaceholderError``."""
    values: list[str] = []
    for name in template.placeholders:
        if name not in params:
            raise MissingPlaceholderError(template.key, name)
        value = params[name]
        values.append(one_line(value) if template.channel is Channel.WHATSAPP else str(value))
    return tuple(values)


PHRASES: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        ("business", "en"): "your business",
        ("business", "hi"): "आपका व्यवसाय",
        ("businesses", "en"): "your businesses",
        ("businesses", "hi"): "आपके व्यवसाय",
        ("firm", "en"): "your firm",
        ("firm", "hi"): "आपकी फ़र्म",
        ("no_due_date", "en"): "no fixed date",
        ("no_due_date", "hi"): "कोई तय तिथि नहीं",
        ("no_steps", "en"): "see the details",
        ("no_steps", "hi"): "विवरण देखें",
        ("rulebook", "en"): "the ComplianceWatch rulebook",
        ("rulebook", "hi"): "ComplianceWatch नियम-पुस्तिका",
        ("more", "en"): "and {count} more",
        ("more", "hi"): "और {count} अन्य",
        ("closed.profile_changed", "en"): "your business profile changed",
        ("closed.profile_changed", "hi"): "आपकी व्यवसाय प्रोफ़ाइल बदल गई",
        ("closed.rule_superseded", "en"): "a newer version of the rule replaced it",
        ("closed.rule_superseded", "hi"): "नियम के नए संस्करण ने इसकी जगह ली",
    }
)
"""What a message says in place of a value it does not have, and the other short phrases the
service fills into a template: by name and language."""


def phrase(name: str, language: str) -> str:
    """The phrase in ``language``, or in English when that language has none."""
    found = PHRASES.get((name, language)) or PHRASES.get((name, "en"))
    if found is None:
        raise UnknownTemplateError(f"phrase {name}", language)
    return found


MONTHS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        "hi": (
            "जनवरी",
            "फ़रवरी",
            "मार्च",
            "अप्रैल",
            "मई",
            "जून",
            "जुलाई",
            "अगस्त",
            "सितंबर",
            "अक्टूबर",
            "नवंबर",
            "दिसंबर",
        ),
    }
)
"""Month names as dates in messages spell them, such as '25 Oct 2026', by language."""


def month_name(month: int, language: str) -> str:
    """The name of ``month`` (1 to 12) in ``language``, or in English when it has none."""
    return (MONTHS.get(language) or MONTHS["en"])[month - 1]


SUMMARY_LINES: Mapping[tuple[str, str], str] = MappingProxyType(
    {
        (CHANGE_CARD, "en"): "New - {title}",
        (CHANGE_CARD, "hi"): "नया - {title}",
        (CREATED, "en"): "New - {title}",
        (CREATED, "hi"): "नया - {title}",
        (DUE_SOON, "en"): "Due {due_date} - {title}",
        (DUE_SOON, "hi"): "अंतिम तिथि {due_date} - {title}",
        (CLOSED, "en"): "Closed - {title}",
        (CLOSED, "hi"): "बंद - {title}",
        (WITHDRAWN, "en"): "No longer applies - {title}",
        (WITHDRAWN, "hi"): "अब लागू नहीं - {title}",
        (DEADLINE_EXTENDED, "en"): "Now due {new_due_date} - {title}",
        (DEADLINE_EXTENDED, "hi"): "नई अंतिम तिथि {new_due_date} - {title}",
        (CORRECTED, "en"): "Due date corrected to {new_due_date} - {title}",
        (CORRECTED, "hi"): "सुधरी अंतिम तिथि {new_due_date} - {title}",
    }
)
"""One notification as a line of a summary or a digest, by its template key and language."""


def summary_line(key: str, language: str, params: Mapping[str, object]) -> str:
    """The notification's line in ``language`` (English when that language has none), filled
    from its values. A key without a line, or values that miss one of its placeholders, give
    the title alone, or the key when there is no title either."""
    line = SUMMARY_LINES.get((key, language)) or SUMMARY_LINES.get((key, "en"))
    if line is not None:
        names = [name for _, name, _, _ in string.Formatter().parse(line) if name is not None]
        if all(name in params for name in names):
            return line.format(**{name: str(params[name]) for name in names})
    return str(params.get("title") or key)
