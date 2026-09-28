"""Knowledge entities and rule relations: the vocabulary of the rulebook's knowledge tables.

An entity is a thing a clause can name and a question can ask about: a notification, a circular,
a section of an Act, a rule of the Rules, a form, an HSN or SAC code, a tax rate, a threshold
amount, a state. ``normalise_name`` maps the many spellings of one entity to one canonical name.
``EntityRef`` carries that name, and the entity's id once alignment has resolved it. ``Mention``
records where a clause names an entity, and ``RuleRelation`` is a typed link from a rule version
to another rule version or to an entity, backed by the clause that states it.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from domain_kernel._validation import require_instance, require_int, require_text
from domain_kernel.citations import DASHES
from domain_kernel.errors import InvalidRelationError, InvariantViolationError
from domain_kernel.ids import CanonicalEntityId, ClauseId, RuleVersionId

RULE_VERSION_KIND = "rule_version"
"""``RuleRelation.to_kind`` when the target is a rule version rather than an entity."""


class EntityType(StrEnum):
    """The ten kinds of entity the knowledge tables hold. Values match the ``type`` column."""

    NOTIFICATION = "notification"
    CIRCULAR = "circular"
    SECTION = "section"
    RULE = "rule"
    FORM = "form"
    HSN_CODE = "hsn_code"
    SAC_CODE = "sac_code"
    TAX_RATE = "tax_rate"
    THRESHOLD = "threshold"
    STATE = "state"


class Instrument(StrEnum):
    """The statute a section or rule number belongs to, written after ``@`` in its canonical
    name: section 39(1) of the CGST Act is ``39(1)@cgst-act``. A bare number is ambiguous
    (section 16 of the CGST Act is not section 16 of the IGST Act), so alignment wants one."""

    CGST_ACT = "cgst-act"
    IGST_ACT = "igst-act"
    UTGST_ACT = "utgst-act"
    CGST_RULES = "cgst-rules"


class RelationKind(StrEnum):
    """How a rule version relates to another rule version or to an entity.

    ``supersedes`` replaces a version from an effective date; ``amends`` changes part of it;
    ``refers_to`` cites it or an entity; ``exempts`` carves something out of it;
    ``extends_deadline`` moves the due date of a period; ``corrects`` replaces what an earlier
    version said (a corrigendum); ``withdraws`` rescinds it.
    """

    SUPERSEDES = "supersedes"
    AMENDS = "amends"
    REFERS_TO = "refers_to"
    EXEMPTS = "exempts"
    EXTENDS_DEADLINE = "extends_deadline"
    CORRECTS = "corrects"
    WITHDRAWS = "withdraws"


RULE_VERSION_ONLY = frozenset(
    {
        RelationKind.SUPERSEDES,
        RelationKind.EXTENDS_DEADLINE,
        RelationKind.CORRECTS,
        RelationKind.WITHDRAWS,
    }
)
"""Relations whose target must be a rule version; ``amends``, ``refers_to`` and ``exempts`` may
also target an entity."""

_DOCUMENT_NUMBER_PREFIX = re.compile(
    r"^(?:(?:notification|circular)\b\s*|no\.\s*|no\b\s*|number\b\s*)+"
)
_AROUND_PUNCTUATION = re.compile(r"\s*([-/])\s*")
_NOT_A_LETTER = r"(?![^\W\d_])"
_SECTION_PREFIX = re.compile(rf"^(?:(?:section|sec){_NOT_A_LETTER}\.?)+", re.IGNORECASE)
_RULE_PREFIX = re.compile(rf"^(?:rule{_NOT_A_LETTER})+", re.IGNORECASE)
_FORM_PREFIX = re.compile(r"^(?:FORM\b-*)+")
_SEPARATORS = re.compile(r"[\s-]+")
_NON_DIGIT = re.compile(r"\D", re.ASCII)
_TRAILING_FRACTION = re.compile(r"\.\d+(?=\D*\Z)", re.ASCII)
_NUMBER = re.compile(r"\d+(?:\.\d+)?|\.\d+", re.ASCII)
_TWO_DIGIT_CODE = re.compile(r"\d{2}", re.ASCII)
_DASH_TO_HYPHEN = str.maketrans(dict.fromkeys(DASHES, "-"))
_RATE_SUFFIX = re.compile(r"\s*\(\s*rate\s*\)")
_LETTERS_BEFORE_DIGIT = re.compile(r"(?<![A-Z])([A-Z]+)(?=[0-9])")
_SCALES: Mapping[str, int] = {
    "lakh": 10**5,
    "lakhs": 10**5,
    "lac": 10**5,
    "lacs": 10**5,
    "crore": 10**7,
    "crores": 10**7,
}
_SCALE_WORD = re.compile(r"\b(?:lakhs?|lacs?|crores?)\b")
_SCALED_AMOUNT = re.compile(
    r"(?:(?:rs\.?|inr|\u20b9)\s*)?([0-9][0-9,]*(?:\.[0-9]+)?)\s*(lakhs?|lacs?|crores?)"
    r"(?:\s+rupees)?\.?"
)


def _collapse(text: str) -> str:
    """Single spaces between words, none at the ends."""
    return " ".join(text.split())


def _squash(text: str) -> str:
    """No whitespace at all."""
    return "".join(text.split())


def _document_number(text: str) -> str:
    """Casefold, drop a leading "notification no.", "circular no." or "no.", close the spaces
    around "-" and "/", and write a "(Rate)" suffix one way: ``17/2026-central tax``,
    ``11/2017-central tax (rate)``."""
    text = _DOCUMENT_NUMBER_PREFIX.sub("", _collapse(text.casefold()))
    text = _AROUND_PUNCTUATION.sub(r"\1", text)
    return _RATE_SUFFIX.sub(" (rate)", text)


def _provision(text: str, prefix: re.Pattern[str]) -> str:
    """The number before the first ``@`` without spaces or its "Section"/"Rule" word, then the
    instrument after it casefolded without spaces; empty when the number is."""
    head, at, instrument = text.partition("@")
    number = prefix.sub("", _squash(head))
    qualifier = _squash(instrument).casefold()
    return f"{number}@{qualifier}" if number and at and qualifier else number


def _section(text: str) -> str:
    """Drop every space, then a leading "Section" or "Sec." that does not start a longer word:
    ``section 16 (2) (c)`` becomes ``16(2)(c)``; ``sections 16 and 17`` keeps its letters. An
    instrument after ``@`` stays: ``16(2)(c)@cgst-act``."""
    return _provision(text, _SECTION_PREFIX)


def _rule(text: str) -> str:
    """Drop every space, then a leading "Rule" that does not start a longer word: ``36(4)``,
    or ``36(4)@cgst-rules`` with an instrument."""
    return _provision(text, _RULE_PREFIX)


def _form(text: str) -> str:
    """Uppercase, one hyphen between parts and none at the ends, a hyphen between the letters
    and the digits of a code, then drop a leading "Form" (however often it repeats) and trim
    again: ``GSTR-3B`` from "gstr 3b" and from "GSTR3B"."""
    text = _SEPARATORS.sub("-", _collapse(text).upper()).strip("-")
    text = _LETTERS_BEFORE_DIGIT.sub(r"\1-", text)
    return _FORM_PREFIX.sub("", text).strip("-")


def _digits(text: str) -> str:
    """ASCII digits only: ``HSN 8471 90`` becomes ``847190``."""
    return _NON_DIGIT.sub("", text)


def _amount(text: str) -> str:
    """Whole rupees as ASCII digits. With "lakh" or "crore" the text must be exactly one scaled
    amount (``Rs. 2 crore`` becomes ``20000000``, ``1.5 lakh`` ``150000``), anything else with
    a scale word gives the empty string. Without one, a trailing fraction (paise) goes first,
    then every other character: ``Rs. 5,00,00,000.50`` becomes ``50000000``."""
    folded = _collapse(text.casefold())
    if _SCALE_WORD.search(folded):
        match = _SCALED_AMOUNT.fullmatch(folded)
        if match is None:
            return ""
        number = Decimal(match.group(1).replace(",", ""))
        return str(int(number * _SCALES[match.group(2)]))
    return _digits(_TRAILING_FRACTION.sub("", text))


def _rate(text: str) -> str:
    """The first number, without leading or trailing zeros, plus ``%``; a bare ``.5`` reads as
    ``0.5``; empty when there is no number."""
    match = _NUMBER.search(text)
    if match is None:
        return ""
    integer, _, fraction = match.group().partition(".")
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    return f"{integer}.{fraction}%" if fraction else f"{integer}%"


def _state(text: str) -> str:
    """A two-digit GST state code as is; a state name casefolded."""
    text = _collapse(text)
    return text if _TWO_DIGIT_CODE.fullmatch(text) else text.casefold()


_NORMALISERS: Mapping[EntityType, Callable[[str], str]] = {
    EntityType.NOTIFICATION: _document_number,
    EntityType.CIRCULAR: _document_number,
    EntityType.SECTION: _section,
    EntityType.RULE: _rule,
    EntityType.FORM: _form,
    EntityType.HSN_CODE: _digits,
    EntityType.SAC_CODE: _digits,
    EntityType.TAX_RATE: _rate,
    EntityType.THRESHOLD: _amount,
    EntityType.STATE: _state,
}


def qualified_name(provision: str, instrument: Instrument) -> str:
    """A section or rule number with its instrument: ``qualified_name("39(1)", CGST_ACT)`` is
    ``39(1)@cgst-act``. ``provision`` is the number as ``normalise_name`` gives it."""
    number = require_text(provision, "provision")
    return f"{number}@{require_instance(instrument, Instrument, 'instrument').value}"


def normalise_name(type: EntityType, text: str) -> str:
    """The canonical name of ``text`` read as an entity of ``type``.

    Deterministic and idempotent. Every Unicode dash (en dash, em dash, minus sign, ...) reads as
    ``-`` and whitespace is collapsed first for every type, so neither the dash a PDF uses nor
    the spacing of the source text matters. Per type:

    - ``notification``, ``circular``: casefold, drop a leading "Notification No.", "Circular
      No.", "No." or "Number", and close the spaces around "-" and "/", so "Notification No.
      17/2026 - Central Tax" and "17/2026-central tax" both give ``17/2026-central tax``; a
      "(Rate)" suffix is always `` (rate)``.
      Abbreviations ("Notfn.", "CT" for "Central Tax") are not expanded: they are alias-table
      work, not normalisation.
    - ``section``, ``rule``: drop every space, then a leading "Section", "Sec." or "Rule" that
      does not start a longer word (``16(2)(c)``, ``36(4)``); "sections" and "sectional" keep
      their letters. The statute goes after ``@`` (``39(1)@cgst-act``, see ``Instrument``).
    - ``form``: uppercase, one hyphen between parts and between the letters and digits of a
      code, none at either end, no leading "Form" (``GSTR-3B`` from "- Form GSTR 3B", from
      "gstr 3b" and from "GSTR3B").
    - ``hsn_code``, ``sac_code``: ASCII digits only (``847190`` from "8471.90").
    - ``threshold``: an amount in rupees; a trailing fraction (paise) is dropped and the ASCII
      digits kept (``50000000`` from "Rs. 5,00,00,000.50"). One amount in lakh or crore is
      scaled (``20000000`` from "Rs. 2 crore"); any other text with a scale word ("two crore",
      "2 crore 50 lakh") gives the empty string rather than a wrong number.
    - ``tax_rate``: the first number without leading or trailing zeros, plus ``%`` (``18%``;
      ``0.5%`` from ".5%").
    - ``state``: a two-digit state code as is, a name casefolded (``29``, ``karnataka``).

    Digits are ASCII: callers pass ASCII digits. Devanagari and fullwidth digits do not count
    as digits, so a code, amount or rate written in them normalises to the empty string. The
    result is empty when nothing is left, such as a rate with no number; ``EntityRef`` rejects
    an empty name.
    """
    kind = require_instance(type, EntityType, "type")
    return _NORMALISERS[kind](require_instance(text, str, "text").translate(_DASH_TO_HYPHEN))


@dataclass(frozen=True, slots=True)
class EntityRef:
    """A canonical entity by type and name, with its id once alignment has resolved it."""

    type: EntityType
    canonical_name: str
    entity_id: CanonicalEntityId | None = None

    def __post_init__(self) -> None:
        kind = require_instance(self.type, EntityType, "type")
        name = require_text(self.canonical_name, "canonical_name")
        canonical = normalise_name(kind, name)
        if name != canonical:
            raise InvariantViolationError(
                f"canonical_name must be normalised: {name!r} normalises to {canonical!r}"
            )
        if self.entity_id is not None:
            require_instance(self.entity_id, CanonicalEntityId, "entity_id")


@dataclass(frozen=True, slots=True)
class Mention:
    """Where a clause names an entity: the verbatim text and its half-open character span."""

    clause_id: ClauseId
    entity: EntityRef
    text: str
    span_start: int
    span_end: int

    def __post_init__(self) -> None:
        require_instance(self.clause_id, ClauseId, "clause_id")
        require_instance(self.entity, EntityRef, "entity")
        require_text(self.text, "text", strip=False)
        start = require_int(self.span_start, "span_start", minimum=0)
        end = require_int(self.span_end, "span_end")
        if end <= start:
            raise InvariantViolationError(
                f"span_end must be greater than span_start, got {start}..{end}"
            )


@dataclass(frozen=True, slots=True)
class RuleRelation:
    """A typed link from a rule version to another rule version or to an entity, with the
    clause that is the evidence for it.

    ``supersedes``, ``extends_deadline``, ``corrects`` and ``withdraws`` target a rule version;
    ``amends``, ``refers_to`` and ``exempts`` target a rule version or an entity. A rule version
    never relates to itself.
    """

    from_rule_version_id: RuleVersionId
    relation: RelationKind
    target: EntityRef | RuleVersionId
    evidence_clause_id: ClauseId

    def __post_init__(self) -> None:
        require_instance(self.from_rule_version_id, RuleVersionId, "from_rule_version_id")
        relation = require_instance(self.relation, RelationKind, "relation")
        require_instance(self.evidence_clause_id, ClauseId, "evidence_clause_id")
        target: object = self.target
        if isinstance(target, RuleVersionId):
            if target == self.from_rule_version_id:
                raise InvalidRelationError(
                    f"{relation.value}: a rule version cannot relate to itself"
                )
        elif isinstance(target, EntityRef):
            if relation in RULE_VERSION_ONLY:
                raise InvalidRelationError(
                    f"{relation.value} must target a rule version, got entity type "
                    f"{target.type.value!r}"
                )
        else:
            raise InvariantViolationError(
                f"target must be EntityRef or RuleVersionId, got {target.__class__.__name__}"
            )

    @property
    def to_kind(self) -> str:
        """``rule_version`` or the entity type value; what the ``to_kind`` column stores."""
        if isinstance(self.target, RuleVersionId):
            return RULE_VERSION_KIND
        return self.target.type.value

    @property
    def to_ref(self) -> str:
        """The rule version id as text or the entity's canonical name; the ``to_ref`` column."""
        if isinstance(self.target, RuleVersionId):
            return str(self.target)
        return self.target.canonical_name
