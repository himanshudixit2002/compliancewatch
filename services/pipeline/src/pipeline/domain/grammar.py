"""The mention grammar: which entities a clause names, found with patterns and no model.

The patterns run on the clause text exactly as parsed, so a match's span is a half-open range of
code points into that text and ``clause.text[start:end]`` is the mention. Extraction noise in
regulator PDFs (an en dash for a hyphen, "sub -section", doubled spaces) is absorbed by the
patterns themselves, never by rewriting the text, so the spans stay true.

Each match carries the name alignment looks up: the kernel's ``normalise_name`` of what the
pattern read, with a section or rule qualified by its statute (``39(1)@cgst-act``) when the
clause or the document says which one. A name the grammar cannot complete (a section of an Act
it does not know, an amount in words) is still reported, and alignment sends it to review.

The grammar knows notifications and circulars (English, and notification numbers in Hindi),
sections and sub-sections, rules and sub-rules, GST forms, HSN and SAC codes after their
keyword, tax rates near a tax word, rupee amounts near a threshold word, and the names of the
states and union territories.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from domain_kernel.citations import DASHES
from domain_kernel.documents import ParsedDocument
from domain_kernel.knowledge import EntityType, Instrument, normalise_name, qualified_name

GRAMMAR_VERSION = "grammar@1"
"""Names the grammar in stored mentions; bump it with any change to what it finds."""

_DASH = "[-" + DASHES + "]"
_SERIES = {
    "central tax": "central tax",
    "integrated tax": "integrated tax",
    "union territory tax": "union territory tax",
    "compensation cess": "compensation cess",
    "ct": "central tax",
    "it": "integrated tax",
    "utt": "union territory tax",
}
_HINDI_SERIES = ("केन्द्रीय कर",)
"""The Hindi series words the notification pattern reads: Central Tax."""

_NOTIFICATION = re.compile(
    r"(?:\b(?:notifications?|notfn\.?)\s*(?:no\.?\s*|number\s+)?|\bno\.\s*|\bnumber\s+)?"
    r"\b(?P<number>\d{1,3})\s*/\s*(?P<year>(?:19|20)\d{2})\s*" + _DASH + r"\s*"
    r"(?P<series>central\s+tax|integrated\s+tax|union\s+territory\s+tax|compensation\s+cess"
    r"|ct|it|utt)\b(?P<rate>\s*\(\s*rate\s*\))?",
    re.IGNORECASE,
)
_HINDI_NOTIFICATION = re.compile(
    r"सं\.\s*(?P<number>\d{1,3})\s*/\s*(?P<year>(?:19|20)\d{2})\s*" + _DASH + r"\s*"
    r"(?P<series>" + "|".join(_HINDI_SERIES) + r")"
)
_CIRCULAR = re.compile(
    r"\bcircular\s*(?:no\.?\s*)?(?P<number>\d{1,4})\s*/\s*(?P<file>\d{1,3})\s*/\s*"
    r"(?P<year>(?:19|20)\d{2})(?:\s*" + _DASH + r"\s*(?P<suffix>c?gst|igst)\b)?",
    re.IGNORECASE,
)
_SUB = r"\(\s*(?P<sub>\d{1,3}[A-Z]?)\s*\)"
_CLAUSE = r"(?:clause\s*\(\s*(?P<clause>[ivxlc]{1,6}|[a-z]{1,2}|\d{1,3})\s*\)\s+of\s+)?"
_SUBSECTION = re.compile(
    _CLAUSE
    + r"\bsub\s*"
    + _DASH
    + r"?\s*section\s*"
    + _SUB
    + r"\s+of\s+section\s+(?P<number>\d{1,3}[A-Z]{0,2})\b",
    re.IGNORECASE,
)
_SECTION = re.compile(
    r"\bsection\s+(?P<number>\d{1,3}[A-Z]{0,2})\b(?P<parts>(?:\s*\(\s*[0-9A-Za-z]{1,4}\s*\))*)",
    re.IGNORECASE,
)
_SUBRULE = re.compile(
    _CLAUSE
    + r"\bsub\s*"
    + _DASH
    + r"?\s*rule\s*"
    + _SUB
    + r"\s+of\s+rule\s+(?P<number>\d{1,3}[A-Z]?)\b",
    re.IGNORECASE,
)
_RULE = re.compile(
    r"\brule\s+(?P<number>\d{1,3}[A-Z]?)\b(?P<parts>(?:\s*\(\s*[0-9A-Za-z]{1,4}\s*\))*)",
    re.IGNORECASE,
)
_GAZETTE_PART = re.compile(r"\bpart\s+[ivx]+\s*,?\s*$", re.IGNORECASE)
_FORM = re.compile(
    r"(?:\bFORM\s+)?\b(?P<code>GSTR\s*" + _DASH + r"?\s*\d{1,2}[A-Z]?"
    r"|GST\s+(?:PMT|REG|CMP|ITC|RFD|DRC)\s*" + _DASH + r"?\s*\d{1,2}[A-Z]?"
    r"|ITC\s*" + _DASH + r"?\s*0?4|CMP\s*" + _DASH + r"?\s*0?8)(?![A-Za-z0-9])"
)
_HSN = re.compile(
    r"\b(?:hsn(?:\s+code)?|tariff\s+item|sub\s*" + _DASH + r"?\s*heading|heading)\s*"
    r"(?:no\.?\s*)?(?P<code>\d{4}(?:[ .]?\d{2}){0,2})(?![0-9])",
    re.IGNORECASE,
)
_SAC = re.compile(
    r"\b(?:sac|services\s+accounting\s+code)\s*(?:no\.?\s*)?(?P<code>99\d{2}(?: ?\d{2})?)(?![0-9])",
    re.IGNORECASE,
)
_RATE = re.compile(r"(?<![0-9.])(?P<rate>\d{1,2}(?:\.\d{1,2})?)\s*(?:%|per\s*cent\b|percent\b)")
_RATE_CONTEXT = re.compile(r"\b(?:rate|tax|cgst|sgst|igst|utgst|cess)\b", re.IGNORECASE)
_AMOUNT = re.compile(
    r"(?:\brs\.?|\binr\b|₹|\brupees)\s*(?P<amount>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?:lakhs?|lacs?|crores?)\b)?",
    re.IGNORECASE,
)
_AMOUNT_CONTEXT = re.compile(
    r"\b(?:turnover|threshold|exceeds?|exceeding|up\s*to|upto|less\s+than|more\s+than)\b",
    re.IGNORECASE,
)
_ACT_NAMES: tuple[tuple[str, Instrument], ...] = (
    (r"central\s+goods\s+and\s+services\s+tax\s+act|cgst\s+act", Instrument.CGST_ACT),
    (r"integrated\s+goods\s+and\s+services\s+tax\s+act|igst\s+act", Instrument.IGST_ACT),
    (
        r"union\s+territory\s+goods\s+and\s+services\s+tax\s+act|utgst\s+act",
        Instrument.UTGST_ACT,
    ),
    (r"central\s+goods\s+and\s+services\s+tax\s+rules|cgst\s+rules", Instrument.CGST_RULES),
)
_OF_THE_INSTRUMENT = re.compile(
    r"\s*,?\s*of\s+the\s+(?P<act>" + "|".join(name for name, _ in _ACT_NAMES) + r")",
    re.IGNORECASE,
)
_INSTRUMENTS = [(re.compile(name, re.IGNORECASE), instrument) for name, instrument in _ACT_NAMES]
_RULES_INSTRUMENTS = frozenset({Instrument.CGST_RULES})

STATE_NAMES: tuple[str, ...] = (
    "Jammu and Kashmir",
    "Himachal Pradesh",
    "Punjab",
    "Chandigarh",
    "Uttarakhand",
    "Haryana",
    "Delhi",
    "Rajasthan",
    "Uttar Pradesh",
    "Bihar",
    "Sikkim",
    "Arunachal Pradesh",
    "Nagaland",
    "Manipur",
    "Mizoram",
    "Tripura",
    "Meghalaya",
    "Assam",
    "West Bengal",
    "Jharkhand",
    "Odisha",
    "Chhattisgarh",
    "Madhya Pradesh",
    "Gujarat",
    "Daman and Diu",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Maharashtra",
    "Andhra Pradesh",
    "Karnataka",
    "Goa",
    "Lakshadweep",
    "Kerala",
    "Tamil Nadu",
    "Puducherry",
    "Andaman and Nicobar Islands",
    "Telangana",
    "Ladakh",
)
"""The states and union territories named in the ontology's ``state_codes`` comments. A state
entity's canonical name is its name casefolded; the two-digit code is alias work in review."""

_STATE = re.compile(
    r"(?<![A-Za-z])(?P<name>"
    + "|".join(
        r"\s+".join(map(re.escape, name.split())) for name in sorted(STATE_NAMES, key=len)[::-1]
    )
    + r")(?![A-Za-z])",
    re.IGNORECASE,
)
_NEW_DELHI = re.compile(r"\bnew\s+$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class GrammarMatch:
    """One mention the grammar found in a text. ``proposed_name`` is empty when the grammar read
    the entity but could not name it canonically; alignment then sends it to review."""

    entity_type: EntityType
    text: str
    span_start: int
    span_end: int
    proposed_name: str
    self_ref: bool = False


@dataclass(frozen=True, slots=True)
class ExtractedMention:
    """A grammar match placed in its clause, as the pipeline hands it to the rulebook."""

    clause_ref: str
    entity_type: EntityType
    text: str
    span_start: int
    span_end: int
    proposed_name: str
    self_ref: bool = False


def find_mentions(
    text: str,
    *,
    language: str = "en",
    default_act: Instrument | None = None,
    own_ref: str = "",
) -> tuple[GrammarMatch, ...]:
    """Every mention in ``text``, in text order, overlaps resolved to the longest match.

    A section or rule takes the statute named right after it ("of the CGST Act"), else the one
    statute of its kind the clause names. A clause that names none falls back to
    ``default_act`` (the document's own series says which); a clause that names two leaves the
    provision unqualified for review. ``own_ref`` ("01/2026-Central Tax") flags the document's
    mentions of itself as ``self_ref``.
    """
    acts = _acts_named(text)
    own_number, own_circular = _own_names(own_ref)
    candidates = [
        *_notifications(text, language, own_number),
        *_circulars(text, own_circular),
        *_provisions(text, EntityType.SECTION, acts, default_act),
        *_provisions(text, EntityType.RULE, acts, default_act),
        *_forms(text),
        *_codes(text),
        *_rates(text),
        *_amounts(text),
        *_states(text),
    ]
    return _longest_first(candidates)


def mentions_for(doc: ParsedDocument, *, own_ref: str = "") -> tuple[ExtractedMention, ...]:
    """The mentions of every clause of ``doc``. ``own_ref`` is the document's own number as the
    source lists it ("01/2026-Central Tax"); its series picks the default statute for sections
    and rules, and its number marks the document's mentions of itself."""
    own = _NOTIFICATION.search(own_ref) if own_ref else None
    default_act = _series_act(own.group("series")) if own else None
    found: list[ExtractedMention] = []
    for clause in doc.clauses:
        language = clause.clause_ref.split(".", 1)[0] if "." in clause.clause_ref else doc.language
        for match in find_mentions(
            clause.text, language=language, default_act=default_act, own_ref=own_ref
        ):
            found.append(
                ExtractedMention(
                    clause_ref=clause.clause_ref,
                    entity_type=match.entity_type,
                    text=match.text,
                    span_start=match.span_start,
                    span_end=match.span_end,
                    proposed_name=match.proposed_name,
                    self_ref=match.self_ref,
                )
            )
    return tuple(found)


def _match(
    text: str,
    entity_type: EntityType,
    start: int,
    end: int,
    name: str,
    *,
    self_ref: bool = False,
) -> GrammarMatch:
    return GrammarMatch(entity_type, text[start:end], start, end, name, self_ref)


def _notifications(text: str, language: str, own_number: str) -> Iterator[GrammarMatch]:
    for match in _NOTIFICATION.finditer(text):
        series = _SERIES[" ".join(match.group("series").casefold().split())]
        rate = " (rate)" if match.group("rate") else ""
        number = f"{match.group('number')}/{match.group('year')}"
        name = normalise_name(EntityType.NOTIFICATION, f"{number}-{series}{rate}")
        yield _match(
            text,
            EntityType.NOTIFICATION,
            match.start(),
            match.end(),
            name,
            self_ref=_same_number(number, own_number),
        )
    if language in {"hi", "mul"}:
        for match in _HINDI_NOTIFICATION.finditer(text):
            number = f"{match.group('number')}/{match.group('year')}"
            name = normalise_name(EntityType.NOTIFICATION, f"{number}-{match.group('series')}")
            yield _match(
                text,
                EntityType.NOTIFICATION,
                match.start(),
                match.end(),
                name,
                self_ref=_same_number(number, own_number),
            )


def _own_names(own_ref: str) -> tuple[str, str]:
    """The document's own notification number ("01/2026") and circular name, when it has one."""
    if not own_ref:
        return "", ""
    notification = _NOTIFICATION.search(own_ref)
    number = (
        f"{int(notification.group('number')):02d}/{notification.group('year')}"
        if notification
        else ""
    )
    return number, "" if notification else normalise_name(EntityType.CIRCULAR, own_ref)


def _same_number(number: str, own_number: str) -> bool:
    if not own_number:
        return False
    first, _, year = number.partition("/")
    return f"{int(first):02d}/{year}" == own_number


def _circulars(text: str, own_circular: str) -> Iterator[GrammarMatch]:
    for match in _CIRCULAR.finditer(text):
        suffix = f"-{match.group('suffix')}" if match.group("suffix") else ""
        raw = f"{match.group('number')}/{match.group('file')}/{match.group('year')}{suffix}"
        name = normalise_name(EntityType.CIRCULAR, raw)
        own = bool(own_circular) and name.split("-")[0] == own_circular.split("-")[0]
        yield _match(text, EntityType.CIRCULAR, match.start(), match.end(), name, self_ref=own)


def _provisions(
    text: str,
    kind: EntityType,
    acts: tuple[Instrument, ...],
    default_act: Instrument | None,
) -> Iterator[GrammarMatch]:
    compound, simple = (_SUBSECTION, _SECTION) if kind is EntityType.SECTION else (_SUBRULE, _RULE)
    for match in compound.finditer(text):
        clause = f"({match.group('clause')})" if match.group("clause") else ""
        number = f"{match.group('number')}({match.group('sub')}){clause}"
        yield _provision(text, kind, match.start(), match.end(), number, acts, default_act)
    for match in simple.finditer(text):
        before = text[max(0, match.start() - 20) : match.start()]
        if kind is EntityType.SECTION and _GAZETTE_PART.search(before):
            continue
        number = match.group("number") + match.group("parts")
        yield _provision(text, kind, match.start(), match.end(), number, acts, default_act)


def _provision(
    text: str,
    kind: EntityType,
    start: int,
    end: int,
    number: str,
    acts: tuple[Instrument, ...],
    default_act: Instrument | None,
) -> GrammarMatch:
    provision = normalise_name(kind, number)
    instrument = _instrument_after(text, end, kind)
    if instrument is None:
        fitting = [act for act in acts if _fits(act, kind)]
        if len(fitting) == 1:
            instrument = fitting[0]
        elif not fitting:
            instrument = _default_for(kind, default_act)
    name = qualified_name(provision, instrument) if provision and instrument else provision
    return _match(text, kind, start, end, name)


def _default_for(kind: EntityType, default_act: Instrument | None) -> Instrument | None:
    """The document's statute for a provision whose clause names none: its own Act for a
    section; for a rule, the CGST Rules when the document is a Central Tax one."""
    if kind is EntityType.SECTION:
        return default_act
    return Instrument.CGST_RULES if default_act is Instrument.CGST_ACT else None


def _instrument_after(text: str, end: int, kind: EntityType) -> Instrument | None:
    """The statute named right after the provision: "section 39 of the CGST Act"."""
    match = _OF_THE_INSTRUMENT.match(text, end)
    if match is None:
        return None
    instrument = _instrument_named(match.group("act"))
    return instrument if _fits(instrument, kind) else None


def _fits(instrument: Instrument | None, kind: EntityType) -> bool:
    if instrument is None:
        return False
    return (instrument in _RULES_INSTRUMENTS) == (kind is EntityType.RULE)


def _acts_named(text: str) -> tuple[Instrument, ...]:
    return tuple(instrument for pattern, instrument in _INSTRUMENTS if pattern.search(text))


def _instrument_named(name: str) -> Instrument | None:
    return next((act for pattern, act in _INSTRUMENTS if pattern.fullmatch(name)), None)


def _series_act(series: str) -> Instrument | None:
    series = _SERIES[" ".join(series.casefold().split())]
    return {
        "central tax": Instrument.CGST_ACT,
        "integrated tax": Instrument.IGST_ACT,
        "union territory tax": Instrument.UTGST_ACT,
    }.get(series)


def _forms(text: str) -> Iterator[GrammarMatch]:
    for match in _FORM.finditer(text):
        name = normalise_name(EntityType.FORM, match.group("code"))
        yield _match(text, EntityType.FORM, match.start(), match.end(), name)


def _codes(text: str) -> Iterator[GrammarMatch]:
    for pattern, kind in ((_HSN, EntityType.HSN_CODE), (_SAC, EntityType.SAC_CODE)):
        for match in pattern.finditer(text):
            name = normalise_name(kind, match.group("code"))
            if len(name) in {4, 6, 8}:
                yield _match(text, kind, match.start(), match.end(), name)


def _rates(text: str) -> Iterator[GrammarMatch]:
    for match in _RATE.finditer(text):
        if _RATE_CONTEXT.search(text[max(0, match.start() - 40) : match.start()]):
            name = normalise_name(EntityType.TAX_RATE, match.group("rate"))
            yield _match(text, EntityType.TAX_RATE, match.start(), match.end(), name)


def _amounts(text: str) -> Iterator[GrammarMatch]:
    for match in _AMOUNT.finditer(text):
        if _AMOUNT_CONTEXT.search(text[max(0, match.start() - 60) : match.start()]):
            name = normalise_name(EntityType.THRESHOLD, match.group())
            yield _match(text, EntityType.THRESHOLD, match.start(), match.end(), name)


def _states(text: str) -> Iterator[GrammarMatch]:
    for match in _STATE.finditer(text):
        name = " ".join(match.group("name").split())
        if name.casefold() == "delhi" and _NEW_DELHI.search(text[: match.start()]):
            continue
        yield _match(
            text,
            EntityType.STATE,
            match.start(),
            match.end(),
            normalise_name(EntityType.STATE, name),
        )


def _longest_first(candidates: Iterable[GrammarMatch]) -> tuple[GrammarMatch, ...]:
    """Keep the longest of overlapping matches (the earliest on a tie), then sort by position."""
    kept: list[GrammarMatch] = []
    ordered = sorted(candidates, key=lambda m: (-(m.span_end - m.span_start), m.span_start))
    for match in ordered:
        if all(match.span_end <= k.span_start or match.span_start >= k.span_end for k in kept):
            kept.append(match)
    return tuple(sorted(kept, key=lambda m: m.span_start))
