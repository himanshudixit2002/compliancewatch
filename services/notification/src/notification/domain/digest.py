"""Several notifications to one person as one message: a batch summary or a digest.

``compose(items, channel, recipient, digest=...)`` picks the template and fills its values:

- ``batch_summary`` for the notifications gathered within the batching window, such as the
  closures and creations one profile change makes;
- with ``digest``, ``ca_digest`` for a CA firm's people and ``daily_digest`` for everyone else.

Every notification becomes one line (``templates.summary_line``), prefixed with the recipient's
label for its business in a digest or when the lines span businesses. The values are ``count``
(notifications), ``client_count`` (businesses) and ``lines``, plus ``business_name`` for a batch
summary and ``org_label`` for a CA firm's digest; the caller adds ``link``.

WhatsApp lines are joined with '; ' and flattened to one line each, because Meta refuses a
template parameter with a newline; email lines are joined with newlines. A list longer than the
policy's ``max_lines`` lines or ``max_param_chars`` characters ends in 'and N more'.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from domain_kernel._validation import freeze_mapping, require_instance, require_text
from domain_kernel.channels import Channel
from domain_kernel.errors import InvariantViolationError
from domain_kernel.ids import BusinessId
from notification.domain.policy import DEFAULT_BATCH_POLICY, BatchPolicy
from notification.domain.recipients import CA_ROLES, Recipient
from notification.domain.templates import (
    BATCH_SUMMARY,
    CA_DIGEST,
    DAILY_DIGEST,
    one_line,
    phrase,
    summary_line,
)

WHATSAPP_SEPARATOR = "; "
EMAIL_SEPARATOR = "\n"
ELLIPSIS = "..."


@dataclass(frozen=True, slots=True)
class SummaryItem:
    """One notification as a summary sees it: its business, template and values."""

    business_id: BusinessId
    template_key: str
    params: Mapping[str, object] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        require_instance(self.business_id, BusinessId, "business_id")
        require_text(self.template_key, "template_key")
        object.__setattr__(self, "params", freeze_mapping(self.params, "params"))


@dataclass(frozen=True, slots=True)
class Composition:
    template_key: str
    params: Mapping[str, object]


def summary_key(recipient: Recipient, *, digest: bool) -> str:
    """The template of a summary for ``recipient``: a batch, or its kind of digest."""
    if not digest:
        return BATCH_SUMMARY
    return CA_DIGEST if recipient.role in CA_ROLES else DAILY_DIGEST


def compose(
    items: Sequence[SummaryItem],
    channel: Channel,
    recipient: Recipient,
    *,
    digest: bool = False,
    language: str | None = None,
    policy: BatchPolicy = DEFAULT_BATCH_POLICY,
) -> Composition:
    """The summary of ``items`` in the recipient's language (or ``language``), in order."""
    if not items:
        raise InvariantViolationError("a summary needs at least one notification")
    language = language or recipient.language
    businesses = list(dict.fromkeys(item.business_id for item in items))
    labelled = digest or len(businesses) > 1
    lines: list[str] = []
    for item in items:
        line = summary_line(item.template_key, language, item.params)
        label = recipient.label_for(item.business_id)
        if labelled and label:
            line = f"{label}: {line}"
        lines.append(one_line(line))
    more = phrase("more", language)
    text = join_lines(
        lines,
        WHATSAPP_SEPARATOR if channel is Channel.WHATSAPP else EMAIL_SEPARATOR,
        lambda count: more.format(count=count),
        policy,
    )
    key = summary_key(recipient, digest=digest)
    params: dict[str, object] = {
        "count": len(items),
        "client_count": len(businesses),
        "lines": text,
    }
    if key == BATCH_SUMMARY:
        params["business_name"] = (
            recipient.label_for(businesses[0]) or phrase("business", language)
            if len(businesses) == 1
            else phrase("businesses", language)
        )
    elif key == CA_DIGEST:
        params["org_label"] = recipient.org_label or phrase("firm", language)
    return Composition(key, params)


def join_lines(
    lines: Sequence[str], separator: str, more: Callable[[int], str], policy: BatchPolicy
) -> str:
    """``lines`` joined by ``separator``: at most ``policy.max_lines`` of them and at most
    ``policy.max_param_chars`` characters in all, the rest counted by ``more(n)``."""
    total = len(lines)
    kept: list[str] = []
    for line in lines:
        if len(kept) == policy.max_lines:
            break
        rest = total - len(kept) - 1
        tail = [more(rest)] if rest else []
        if len(separator.join([*kept, line, *tail])) > policy.max_param_chars:
            break
        kept.append(line)
    hidden = total - len(kept)
    if not kept:
        # Not even the first line fits beside its tail: it is cut short.
        tail = [more(hidden - 1)] if hidden > 1 else []
        room = policy.max_param_chars - len(separator.join(["", *tail])) - len(ELLIPSIS)
        kept.append(lines[0][: max(room, 0)].rstrip() + ELLIPSIS)
        return separator.join([*kept, *tail])
    if hidden:
        kept.append(more(hidden))
    return separator.join(kept)
