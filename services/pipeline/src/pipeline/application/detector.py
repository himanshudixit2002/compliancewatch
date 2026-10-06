"""What a parsed document is, how sure that reading is, and what it does to earlier documents.

The detector runs before extraction and needs no model: it reads the title and the first
clauses for the words regulators use. It answers these questions. Which kind of document is
this (a notification, a circular, a press release, an act amendment), and how sure is that: the
opening names the type its source publishes (``certain``), names no type at all so the source's
is taken (``default``), or names another type (``conflict``, which a person triages)? Is it a
regulatory document at all, or a portal user manual listed among the notices (``relevance``)?
Does it change an earlier document, and how (a corrigendum corrects, a rescission withdraws, an
amendment amends, an extension moves a due date)? Which earlier documents does it name? A press
release announces what the Council recommended, which is not in force until a notification says
so, and the detector marks it.

The type is the one the opening names first: a notification that later quotes "the
recommendations of the Council" is a notification. A type a person gave (an uploader's, a
triage's) is taken as it is, and so is a statute source's: no marker overrules a person, and an
Act or the Rules quote notifications throughout.

The title a document is listed under (a crawl's listing, an uploader's) is the one the rulebook
registers it with, so the relevance is read from it when there is one: a portal's user manual is
listed as one even when its cover line is too short to be the PDF's title. The type is read from
the document's own opening, never from the listing, which names the notifications a circular
clarifies or a notification amends.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from domain_kernel.citations import DASHES
from domain_kernel.documents import DocumentType, ParsedDocument
from domain_kernel.knowledge import EntityType, normalise_name
from pipeline.domain.classification import Relevance, TypeConfidence, reasons_of

CLAUSES_TO_READ = 6


class ChangeKind(StrEnum):
    NONE = "none"
    CORRIGENDUM = "corrigendum"
    WITHDRAWAL = "withdrawal"
    AMENDMENT = "amendment"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class Detection:
    """``confidence`` says how sure ``doc_type`` is and ``relevance`` whether the document is a
    regulatory one; ``reasons`` say why, in words, the type's reason first."""

    doc_type: DocumentType
    change_kind: ChangeKind
    references: tuple[str, ...] = field(default=())
    announced_not_in_force: bool = False
    is_advisory: bool = False
    is_user_manual: bool = False
    confidence: TypeConfidence = TypeConfidence.DEFAULT
    relevance: Relevance = Relevance.RELEVANT
    reasons: tuple[str, ...] = field(default=())


_CORRIGENDUM = re.compile(r"\bcorrigend(?:um|a)\b", re.IGNORECASE)
_WITHDRAWAL = re.compile(r"\b(?:rescind|rescission|withdraw(?:n|al|s)?)\b", re.IGNORECASE)
_AMENDMENT = re.compile(r"\b(?:amend(?:s|ed|ment|ments)?|substitut(?:e|ed|ion))\b", re.IGNORECASE)
_EXTENSION = re.compile(
    r"\b(?:extend(?:s|ed|ing)?|extension)\b.{0,80}\b(?:due date|time limit|date|period)\b"
    r"|\b(?:due date|time limit)\b.{0,80}\b(?:extend(?:s|ed|ing)?|extension)\b",
    re.IGNORECASE | re.DOTALL,
)
_DASH = "[-" + DASHES + "]"
_NOTIFICATION_REF = re.compile(
    r"(?:notification|circular)\s+(?:no\.?\s*)?"
    r"(\d{1,3}/\d{4}(?:\s*" + _DASH + r"\s*[A-Za-z ]+?(?:tax|gst)(?:\s*\(rate\))?)?)"
    r"|\b(\d{1,3}/\d{4}\s*" + _DASH + r"\s*(?:central|integrated|union territory)\s+tax"
    r"(?:\s*\(rate\))?)",
    re.IGNORECASE,
)
_CIRCULAR_REF = re.compile(
    r"circular\s+(?:no\.?\s*)?(\d{1,3}/\d{2}/\d{4}(?:\s*" + _DASH + r"\s*GST)?)",
    re.IGNORECASE,
)
_PRESS_RELEASE = re.compile(
    r"\bpress release\b|\bby pib\b|\bpib delhi\b|\b(?:gst )?council (?:meeting|held)\b"
    r"|\bmeeting of the gst council\b|\brecommendations? of the \d+\s*(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)
"""What a press release says of itself. "On the recommendations of the Council", which nearly
every notification says, is not among them."""
_ADVISORY = re.compile(r"\badvisory\b", re.IGNORECASE)
_USER_MANUAL = re.compile(r"\b(?:user manual|how to|faq|frequently asked)\b", re.IGNORECASE)
_NOT_REGULATORY = re.compile(
    r"\b(?:user manual|user guide|how to|step[- ]by[- ]step|tutorial)\b", re.IGNORECASE
)
"""A title that reads as help for the portal, not a regulator's document. An FAQ explains the
law and stays relevant."""
_CIRCULAR = re.compile(r"\bcircular\b", re.IGNORECASE)
_NOTIFICATION = re.compile(r"\bnotification\b", re.IGNORECASE)
_OWN_NUMBER = re.compile(r"^\s*(?:notification|circular)\s+(?:no\.?\s*)?\d", re.IGNORECASE)
_ACT_AMENDMENT = re.compile(r"\b(?:amendment )?act,? \d{4}\b.*\bamend", re.IGNORECASE | re.DOTALL)
OPENING_CHARS = 400
"""How much of the head the type markers are looked for in."""


def detect(
    doc: ParsedDocument,
    *,
    default_type: DocumentType | None = None,
    own_ref: str = "",
    given_type: DocumentType | None = None,
    listed_title: str = "",
) -> Detection:
    """Read ``doc`` and classify it.

    ``default_type`` is what the source usually publishes (``doc.doc_type`` when not given);
    ``given_type`` is a type a person gave (an uploader's, a triage's), which is taken as it is;
    ``own_ref`` is the document's own number as the source listed it ("01/2026-Central Tax"),
    so a gazette text that repeats its own number does not cite itself; ``listed_title`` is the
    title it is listed and registered under, which the relevance and the title's flags are read
    from in place of ``doc.title`` when it is given.
    """
    head = " ".join([doc.title, *(clause.text for clause in doc.clauses[:CLAUSES_TO_READ])])
    title = listed_title.strip() or doc.title
    expected = given_type or default_type or doc.doc_type
    doc_type, confidence, type_reason = _doc_type(
        opening_of(doc), expected, given=given_type is not None
    )
    relevance, relevance_reason = _relevance(title, expected, given=given_type is not None)
    change = _change_kind(head)
    references = tuple(_references(head, exclude=doc.title, own_ref=own_ref))
    return Detection(
        doc_type=doc_type,
        change_kind=change,
        references=references,
        announced_not_in_force=doc_type is DocumentType.PRESS_RELEASE,
        is_advisory=bool(_ADVISORY.search(title)),
        is_user_manual=bool(_USER_MANUAL.search(title)),
        confidence=confidence,
        relevance=relevance,
        reasons=reasons_of((type_reason, relevance_reason)),
    )


def _named(doc_type: DocumentType) -> str:
    return doc_type.value.replace("_", " ")


def opening_of(doc: ParsedDocument) -> str:
    """The first ``OPENING_CHARS`` of the title and the first clauses, where the type markers
    are looked for. A title the first clause starts with (a PDF's title is its first line, cut
    short) is read once, in the clause."""
    clauses = [clause.text for clause in doc.clauses[:CLAUSES_TO_READ]]
    title = doc.title.strip()
    lead = [] if title and clauses and clauses[0].strip().startswith(title) else [doc.title]
    return " ".join([*lead, *clauses])[:OPENING_CHARS]


def _doc_type(
    opening: str, expected: DocumentType, *, given: bool
) -> tuple[DocumentType, TypeConfidence, str]:
    """The type, how sure it is, and why."""
    if given:
        return (
            expected,
            TypeConfidence.CERTAIN,
            f"a person gave its type: {_named(expected)}",
        )
    if expected is DocumentType.STATUTE:
        return (
            expected,
            TypeConfidence.CERTAIN,
            "its source holds statutes, which an analyst uploads",
        )
    found = marked_type(opening)
    if found is None:
        return (
            expected,
            TypeConfidence.DEFAULT,
            f"nothing in its opening names its type, so it is taken as its source's: "
            f"{_named(expected)}",
        )
    if found is expected:
        return (
            found,
            TypeConfidence.CERTAIN,
            f"its opening names it a {_named(found)}, the type its source publishes",
        )
    return (
        found,
        TypeConfidence.CONFLICT,
        f"its opening names it a {_named(found)}, but its source publishes the type "
        f"{_named(expected)}",
    )


def marked_type(opening: str) -> DocumentType | None:
    """The type ``opening`` names first, or None when it names none: a press release by what
    one says of itself, an act amendment by an Act and its year with an amendment, a circular or
    a notification by its name."""
    opening = opening[:OPENING_CHARS]
    found: list[tuple[int, DocumentType]] = []
    press = _PRESS_RELEASE.search(opening)
    if press is not None:
        found.append((press.start(), DocumentType.PRESS_RELEASE))
    act = _ACT_AMENDMENT.search(opening)
    if act is not None and "act" in opening.lower()[:120]:
        found.append((act.start(), DocumentType.ACT_AMENDMENT))
    circular = _CIRCULAR.search(opening)
    if circular is not None:
        found.append((circular.start(), DocumentType.CIRCULAR))
    notification = _NOTIFICATION.search(opening)
    if notification is not None:
        found.append((notification.start(), DocumentType.NOTIFICATION))
    return min(found, key=lambda item: item[0])[1] if found else None


def _relevance(title: str, expected: DocumentType, *, given: bool) -> tuple[Relevance, str]:
    """Whether the document is a regulatory one, and why."""
    if given:
        return Relevance.RELEVANT, f"a person placed it as a {_named(expected)}"
    if expected is DocumentType.STATUTE:
        return Relevance.RELEVANT, "a statute is the law the other documents act on"
    if _NOT_REGULATORY.search(title):
        return (
            Relevance.IRRELEVANT,
            "its title reads as a user manual or a how-to guide for the portal, not a "
            "regulator's document",
        )
    return Relevance.RELEVANT, "its title does not read as a user manual or a how-to guide"


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
