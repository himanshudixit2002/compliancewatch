"""What a parsed document is and what it does to earlier documents.

The detector runs before extraction and needs no model: it reads the title and the first
clauses for the words regulators use. It answers three questions. Which kind of document is
this (a notification, a circular, a press release, an advisory)? Does it change an earlier one,
and how (a corrigendum corrects, a rescission withdraws, an amendment amends, an extension moves
a due date)? Which earlier documents does it name? A press release announces what the Council
recommended, which is not in force until a notification says so, and the detector marks it.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from domain_kernel.documents import DocumentType, ParsedDocument
from domain_kernel.knowledge import EntityType, normalise_name

CLAUSES_TO_READ = 6


class ChangeKind(StrEnum):
    NONE = "none"
    CORRIGENDUM = "corrigendum"
    WITHDRAWAL = "withdrawal"
    AMENDMENT = "amendment"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class Detection:
    doc_type: DocumentType
    change_kind: ChangeKind
    references: tuple[str, ...] = field(default=())
    announced_not_in_force: bool = False
    is_advisory: bool = False
    is_user_manual: bool = False


_CORRIGENDUM = re.compile(r"\bcorrigend(?:um|a)\b", re.IGNORECASE)
_WITHDRAWAL = re.compile(r"\b(?:rescind|rescission|withdraw(?:n|al|s)?)\b", re.IGNORECASE)
_AMENDMENT = re.compile(r"\b(?:amend(?:s|ed|ment|ments)?|substitut(?:e|ed|ion))\b", re.IGNORECASE)
_EXTENSION = re.compile(
    r"\b(?:extend(?:s|ed|ing)?|extension)\b.{0,80}\b(?:due date|time limit|date|period)\b"
    r"|\b(?:due date|time limit)\b.{0,80}\b(?:extend(?:s|ed|ing)?|extension)\b",
    re.IGNORECASE | re.DOTALL,
)
_NOTIFICATION_REF = re.compile(
    r"(?:notification|circular)\s+(?:no\.?\s*)?"
    r"(\d{1,3}/\d{4}(?:\s*-\s*[A-Za-z ]+?(?:tax|gst)(?:\s*\(rate\))?)?)"
    r"|\b(\d{1,3}/\d{4}\s*-\s*(?:central|integrated|union territory)\s+tax(?:\s*\(rate\))?)",
    re.IGNORECASE,
)
_CIRCULAR_REF = re.compile(
    r"circular\s+(?:no\.?\s*)?(\d{1,3}/\d{2}/\d{4}(?:\s*-\s*GST)?)", re.IGNORECASE
)
_PRESS_RELEASE = re.compile(
    r"\b(?:press release|recommendations? of the|council (?:meeting|held))\b", re.IGNORECASE
)
_ADVISORY = re.compile(r"\badvisory\b", re.IGNORECASE)
_USER_MANUAL = re.compile(r"\b(?:user manual|how to|faq|frequently asked)\b", re.IGNORECASE)
_CIRCULAR = re.compile(r"\bcircular\b", re.IGNORECASE)
_NOTIFICATION = re.compile(r"\bnotification\b", re.IGNORECASE)
_OWN_NUMBER = re.compile(r"^\s*(?:notification|circular)\s+(?:no\.?\s*)?\d", re.IGNORECASE)
_ACT_AMENDMENT = re.compile(r"\b(?:amendment )?act,? \d{4}\b.*\bamend", re.IGNORECASE | re.DOTALL)


def detect(
    doc: ParsedDocument, *, default_type: DocumentType | None = None, own_ref: str = ""
) -> Detection:
    """Read ``doc`` and classify it.

    ``default_type`` is what the source usually publishes; ``own_ref`` is the document's own
    number as the source listed it ("01/2026-Central Tax"), so a gazette text that repeats its
    own number does not cite itself.
    """
    head = " ".join([doc.title, *(clause.text for clause in doc.clauses[:CLAUSES_TO_READ])])
    doc_type = _doc_type(head, default_type or doc.doc_type)
    change = _change_kind(head)
    references = tuple(_references(head, exclude=doc.title, own_ref=own_ref))
    return Detection(
        doc_type=doc_type,
        change_kind=change,
        references=references,
        announced_not_in_force=doc_type is DocumentType.PRESS_RELEASE,
        is_advisory=bool(_ADVISORY.search(doc.title)),
        is_user_manual=bool(_USER_MANUAL.search(doc.title)),
    )


def _doc_type(head: str, default: DocumentType) -> DocumentType:
    opening = head[:400]
    if _PRESS_RELEASE.search(opening):
        return DocumentType.PRESS_RELEASE
    if _ACT_AMENDMENT.search(opening) and "act" in opening.lower()[:120]:
        return DocumentType.ACT_AMENDMENT
    if _CIRCULAR.search(opening[:200]) and not _NOTIFICATION.search(opening[:120]):
        return DocumentType.CIRCULAR
    if _NOTIFICATION.search(opening[:200]):
        return DocumentType.NOTIFICATION
    return default


def _change_kind(head: str) -> ChangeKind:
    if _CORRIGENDUM.search(head):
        return ChangeKind.CORRIGENDUM
    if _WITHDRAWAL.search(head):
        return ChangeKind.WITHDRAWAL
    if _EXTENSION.search(head):
        return ChangeKind.EXTENSION
    if _AMENDMENT.search(head):
        return ChangeKind.AMENDMENT
    return ChangeKind.NONE


def _references(head: str, *, exclude: str, own_ref: str = "") -> Iterable[str]:
    """Canonical names of the notifications and circulars the text names, in order, once.

    A title that starts with the document's own number ("Notification No. 01/2026 - Central
    Tax") names itself, and that number is not a reference; a title that names a number after a
    verb ("Seeks to rescind Notification No. 30/2021") is pointing at another document.
    """
    own = {_number_part(m) for m in _numbers(exclude)} if _OWN_NUMBER.match(exclude) else set()
    if own_ref:
        own.add(_number_part(own_ref))
    seen: set[str] = set()
    for raw in _numbers(head):
        name = normalise_name(EntityType.NOTIFICATION, raw)
        if name and name not in seen and _number_part(name) not in own:
            seen.add(name)
            yield name


def _number_part(name: str) -> str:
    """``01/2026`` from ``01/2026-central tax`` or ``Notification No. 01/2026 - Central Tax``."""
    return normalise_name(EntityType.NOTIFICATION, name).split("-", 1)[0].strip()


def _numbers(text: str) -> Iterable[str]:
    for match in _CIRCULAR_REF.finditer(text):
        yield match.group(1)
    for match in _NOTIFICATION_REF.finditer(text):
        yield match.group(1) or match.group(2)
