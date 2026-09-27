from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from domain_kernel.errors import (
    PROBLEM_TYPE_PREFIX,
    DomainError,
    InvalidRelationError,
    InvariantViolationError,
)
from domain_kernel.ids import CanonicalEntityId, ClauseId, EntityId, RuleId, RuleVersionId
from domain_kernel.knowledge import (
    RULE_VERSION_KIND,
    EntityRef,
    EntityType,
    Mention,
    RelationKind,
    RuleRelation,
    normalise_name,
)

ENTITY_TYPES = st.sampled_from(list(EntityType))
# ``st.text()`` on its own almost never puts a separator in front of a prefix word such as
# "form", so the idempotence property missed "- Form GSTR 3B", which used to normalise twice.
# The second strategy builds names the way source text spells them: a separator at either end,
# an optional prefix word and a body over the characters entity names use.
EDGE = st.sampled_from(["", " ", "-", " - ", "--", "\t"])
PREFIX_WORD = st.sampled_from(
    [
        "",
        "Form",
        "form",
        "FORM",
        "Section",
        "sections",
        "Sec.",
        "Rule",
        "rules",
        "No.",
        "Notification No.",
        "Circular",
        "Number",
    ]
)
BODY = st.text(alphabet="GSTRgstr0123456789 -/().%,ab", max_size=12)
NAME_TEXT = st.one_of(st.text(), st.tuples(EDGE, PREFIX_WORD, BODY, EDGE).map("".join))
FORM = EntityRef(EntityType.FORM, "GSTR-3B")
CLAUSE = ClauseId.new()
FROM = RuleVersionId.new()
OTHER = RuleVersionId.new()

# Non-ASCII digits, as escapes so that no confusable character sits in the source: Devanagari
# eight four seven one nine zero, fullwidth nine nine eight three one three, and rupee sign with
# Devanagari five crore in Indian grouping. normalise_name drops them all.
DEVANAGARI_847190 = "\u096e\u096a\u096d\u0967\u096f\u0966"
FULLWIDTH_998313 = "\uff19\uff19\uff18\uff13\uff11\uff13"
DEVANAGARI_FIVE_CRORE = "\u20b9 \u096b,\u0966\u0966,\u0966\u0966,\u0966\u0966\u0966"

CANONICAL_SAMPLES: dict[EntityType, str] = {
    EntityType.NOTIFICATION: "17/2026-central tax",
    EntityType.CIRCULAR: "123/42/2019-gst",
    EntityType.SECTION: "16(2)(c)",
    EntityType.RULE: "36(4)",
    EntityType.FORM: "GSTR-3B",
    EntityType.HSN_CODE: "847190",
    EntityType.SAC_CODE: "998313",
    EntityType.TAX_RATE: "18%",
    EntityType.THRESHOLD: "50000000",
    EntityType.STATE: "29",
}

NAME_TABLE: list[tuple[EntityType, str, str]] = [
    (EntityType.NOTIFICATION, "Notification No. 17/2026-Central Tax", "17/2026-central tax"),
    (EntityType.NOTIFICATION, "Notification No. 17/2026 - Central Tax", "17/2026-central tax"),
    (EntityType.NOTIFICATION, "  notification   no.17/2026-Central Tax ", "17/2026-central tax"),
    (EntityType.NOTIFICATION, "No. 17/2026-Central Tax", "17/2026-central tax"),
    (EntityType.NOTIFICATION, " 17 / 2026 - Central Tax ", "17/2026-central tax"),
    (EntityType.NOTIFICATION, "17/2026-central tax", "17/2026-central tax"),
    (EntityType.NOTIFICATION, "Notification Number 17/2026", "17/2026"),
    (EntityType.NOTIFICATION, "Notfn. 17/2026-CT", "notfn. 17/2026-ct"),
    (EntityType.NOTIFICATION, "November 2026 list", "november 2026 list"),
    (EntityType.CIRCULAR, "Circular No. 123/42/2019-GST", "123/42/2019-gst"),
    (EntityType.CIRCULAR, "Circular No. 123 / 42 / 2019 - GST", "123/42/2019-gst"),
    (EntityType.CIRCULAR, "circular no 123/42/2019-GST", "123/42/2019-gst"),
    (EntityType.CIRCULAR, "CIRCULAR NO.123/42/2019-GST", "123/42/2019-gst"),
    (EntityType.CIRCULAR, "123/42/2019-gst", "123/42/2019-gst"),
    (EntityType.SECTION, "section 16 (2) (c)", "16(2)(c)"),
    (EntityType.SECTION, "Section 16(2)(c)", "16(2)(c)"),
    (EntityType.SECTION, "SECTION 16", "16"),
    (EntityType.SECTION, "Sec. 16(2)(c)", "16(2)(c)"),
    (EntityType.SECTION, "Section16(2)(c)", "16(2)(c)"),
    (EntityType.SECTION, "16 (2) (c)", "16(2)(c)"),
    (EntityType.SECTION, "sections 16 and 17", "sections16and17"),
    (EntityType.SECTION, "sectional 16", "sectional16"),
    (EntityType.RULE, "Rule 36 (4)", "36(4)"),
    (EntityType.RULE, "rule 36(4)", "36(4)"),
    (EntityType.RULE, "Rule36(4)", "36(4)"),
    (EntityType.RULE, "36 (4)", "36(4)"),
    (EntityType.RULE, "rules 36 and 37", "rules36and37"),
    (EntityType.RULE, "ruler 36", "ruler36"),
    (EntityType.FORM, "gstr 3b", "GSTR-3B"),
    (EntityType.FORM, "GSTR-3B", "GSTR-3B"),
    (EntityType.FORM, "Form GSTR 3B", "GSTR-3B"),
    (EntityType.FORM, "FORM  GSTR - 3B", "GSTR-3B"),
    (EntityType.FORM, "- Form GSTR 3B", "GSTR-3B"),
    (EntityType.FORM, " - FORM - GSTR - 3B - ", "GSTR-3B"),
    (EntityType.FORM, "GSTR-3B-", "GSTR-3B"),
    (EntityType.FORM, "Form Form GSTR-1", "GSTR-1"),
    (EntityType.FORM, "gstr-1", "GSTR-1"),
    (EntityType.FORM, "itc 04", "ITC-04"),
    (EntityType.FORM, "forms 1", "FORMS-1"),
    (EntityType.HSN_CODE, "HSN 8471 90", "847190"),
    (EntityType.HSN_CODE, "8471.90", "847190"),
    (EntityType.HSN_CODE, "8471 90 00", "84719000"),
    (EntityType.HSN_CODE, "hsn: 8471", "8471"),
    (EntityType.HSN_CODE, DEVANAGARI_847190, ""),
    (EntityType.SAC_CODE, "SAC 9983", "9983"),
    (EntityType.SAC_CODE, "998313", "998313"),
    (EntityType.SAC_CODE, "99 83 13", "998313"),
    (EntityType.SAC_CODE, FULLWIDTH_998313, ""),
    (EntityType.TAX_RATE, "18 %", "18%"),
    (EntityType.TAX_RATE, "18%", "18%"),
    (EntityType.TAX_RATE, "18", "18%"),
    (EntityType.TAX_RATE, "0.25 %", "0.25%"),
    (EntityType.TAX_RATE, ".5%", "0.5%"),
    (EntityType.TAX_RATE, ".50 %", "0.5%"),
    (EntityType.TAX_RATE, "18.00 per cent", "18%"),
    (EntityType.TAX_RATE, "5.50%", "5.5%"),
    (EntityType.TAX_RATE, "018%", "18%"),
    (EntityType.TAX_RATE, "0%", "0%"),
    (EntityType.THRESHOLD, "Rs. 5,00,00,000", "50000000"),
    (EntityType.THRESHOLD, "Rs.5,00,00,000", "50000000"),
    (EntityType.THRESHOLD, "5,00,00,000.50", "50000000"),
    (EntityType.THRESHOLD, "₹ 5,00,00,000", "50000000"),
    (EntityType.THRESHOLD, "50000000", "50000000"),
    (EntityType.THRESHOLD, "INR 2,00,00,000/-", "20000000"),
    (EntityType.THRESHOLD, "INR 2,00,00,000.50/-", "20000000"),
    (EntityType.THRESHOLD, DEVANAGARI_FIVE_CRORE, ""),
    (EntityType.STATE, "29", "29"),
    (EntityType.STATE, "Karnataka", "karnataka"),
    (EntityType.STATE, " KARNATAKA ", "karnataka"),
    (EntityType.STATE, "07", "07"),
    (EntityType.STATE, "Tamil  Nadu", "tamil nadu"),
]

PAIRING_MATRIX: list[tuple[RelationKind, str, bool]] = [
    (RelationKind.SUPERSEDES, "entity", False),
    (RelationKind.SUPERSEDES, RULE_VERSION_KIND, True),
    (RelationKind.AMENDS, "entity", True),
    (RelationKind.AMENDS, RULE_VERSION_KIND, True),
    (RelationKind.REFERS_TO, "entity", True),
    (RelationKind.REFERS_TO, RULE_VERSION_KIND, True),
    (RelationKind.EXEMPTS, "entity", True),
    (RelationKind.EXEMPTS, RULE_VERSION_KIND, True),
    (RelationKind.EXTENDS_DEADLINE, "entity", False),
    (RelationKind.EXTENDS_DEADLINE, RULE_VERSION_KIND, True),
]


# ---------------------------------------------------------------- enums


def test_entity_type_values_are_the_schema_vocabulary() -> None:
    assert [kind.value for kind in EntityType] == [
        "notification",
        "circular",
        "section",
        "rule",
        "form",
        "hsn_code",
        "sac_code",
        "tax_rate",
        "threshold",
        "state",
    ]
    assert all(kind.value == kind.value.lower() for kind in EntityType)
    assert EntityType("hsn_code") is EntityType.HSN_CODE


def test_relation_kind_values_are_the_schema_vocabulary() -> None:
    assert [kind.value for kind in RelationKind] == [
        "supersedes",
        "amends",
        "refers_to",
        "exempts",
        "extends_deadline",
    ]
    assert RelationKind("extends_deadline") is RelationKind.EXTENDS_DEADLINE


def test_rule_version_kind_is_outside_the_entity_types() -> None:
    assert RULE_VERSION_KIND == "rule_version"
    assert RULE_VERSION_KIND not in {kind.value for kind in EntityType}


def test_every_entity_type_has_a_table_case_and_a_sample() -> None:
    covered = {kind for kind, _, _ in NAME_TABLE}
    assert covered == set(EntityType)
    assert all(sum(kind is entry for entry, _, _ in NAME_TABLE) >= 3 for kind in EntityType)
    assert set(CANONICAL_SAMPLES) == set(EntityType)


# ---------------------------------------------------------------- normalise_name


@pytest.mark.parametrize(("kind", "text", "expected"), NAME_TABLE)
def test_normalise_name_table(kind: EntityType, text: str, expected: str) -> None:
    assert normalise_name(kind, text) == expected


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        (EntityType.NOTIFICATION, "Notification No."),
        (EntityType.CIRCULAR, "  "),
        (EntityType.SECTION, "Section"),
        (EntityType.RULE, "rule"),
        (EntityType.FORM, "form - "),
        (EntityType.FORM, "-form"),
        (EntityType.HSN_CODE, "none"),
        (EntityType.SAC_CODE, ""),
        (EntityType.TAX_RATE, "eighteen per cent"),
        (EntityType.THRESHOLD, "five crore"),
        (EntityType.STATE, ""),
    ],
)
def test_nothing_left_gives_an_empty_name(kind: EntityType, text: str) -> None:
    assert normalise_name(kind, text) == ""


def test_normalise_name_checks_its_arguments() -> None:
    with pytest.raises(InvariantViolationError, match="type must be EntityType"):
        normalise_name("section", "16")  # type: ignore[arg-type]
    with pytest.raises(InvariantViolationError, match="text must be str"):
        normalise_name(EntityType.SECTION, 16)  # type: ignore[arg-type]


@settings(max_examples=1000)
@given(ENTITY_TYPES, NAME_TEXT)
def test_normalise_name_is_idempotent(kind: EntityType, text: str) -> None:
    once = normalise_name(kind, text)
    assert normalise_name(kind, once) == once


@settings(max_examples=1000)
@given(ENTITY_TYPES, NAME_TEXT)
def test_normalise_name_ignores_spacing(kind: EntityType, text: str) -> None:
    expected = normalise_name(kind, text)
    assert normalise_name(kind, f"  {text} \t\n") == expected
    assert normalise_name(kind, text.replace(" ", "  ")) == expected
    assert normalise_name(kind, text.replace(" ", " \n ")) == expected


@settings(max_examples=1000)
@given(ENTITY_TYPES, NAME_TEXT)
def test_normalise_name_output_is_trimmed(kind: EntityType, text: str) -> None:
    name = normalise_name(kind, text)
    assert name == name.strip()
    assert "  " not in name


@settings(max_examples=1000)
@given(ENTITY_TYPES, NAME_TEXT)
def test_every_non_empty_canonical_name_makes_an_entity_ref(kind: EntityType, text: str) -> None:
    name = normalise_name(kind, text)
    if name:
        assert EntityRef(kind, name).canonical_name == name
    else:
        with pytest.raises(InvariantViolationError, match="canonical_name must not be blank"):
            EntityRef(kind, name)


# ---------------------------------------------------------------- CanonicalEntityId


def test_canonical_entity_id_is_its_own_kind() -> None:
    raw = uuid4()
    entity_id = CanonicalEntityId(raw)
    assert isinstance(entity_id, EntityId)
    assert entity_id == CanonicalEntityId.parse(str(raw))
    as_object: object = entity_id
    assert as_object != ClauseId(raw)
    assert CanonicalEntityId.new() != CanonicalEntityId.new()
    assert not hasattr(entity_id, "__dict__")


# ---------------------------------------------------------------- EntityRef


def test_entity_ref_holds_a_canonical_name_and_an_optional_id() -> None:
    entity_id = CanonicalEntityId.new()
    ref = EntityRef(EntityType.SECTION, "16(2)(c)", entity_id)
    assert (ref.type, ref.canonical_name, ref.entity_id) == (
        EntityType.SECTION,
        "16(2)(c)",
        entity_id,
    )
    assert EntityRef(EntityType.SECTION, "16(2)(c)").entity_id is None
    assert hash(ref) == hash(EntityRef(EntityType.SECTION, "16(2)(c)", entity_id))
    assert ref != EntityRef(EntityType.RULE, "16(2)(c)", entity_id)
    with pytest.raises(FrozenInstanceError):
        ref.canonical_name = "17"  # type: ignore[misc]
    assert not hasattr(ref, "__dict__")


@pytest.mark.parametrize("kind", list(EntityType))
def test_entity_ref_accepts_every_sample(kind: EntityType) -> None:
    assert EntityRef(kind, CANONICAL_SAMPLES[kind]).type is kind


@pytest.mark.parametrize(
    ("kind", "text"),
    [
        (EntityType.NOTIFICATION, "No. 17/2026-Central Tax"),
        (EntityType.NOTIFICATION, "17/2026-Central Tax"),
        (EntityType.SECTION, "Section 16"),
        (EntityType.SECTION, "sections 16"),
        (EntityType.THRESHOLD, "5,00,00,000.50"),
        (EntityType.FORM, "gstr 3b"),
        (EntityType.HSN_CODE, "8471 90"),
        (EntityType.TAX_RATE, "18"),
        (EntityType.STATE, "Karnataka"),
    ],
)
def test_entity_ref_rejects_a_name_that_is_not_canonical(kind: EntityType, text: str) -> None:
    with pytest.raises(InvariantViolationError, match="canonical_name must be normalised") as info:
        EntityRef(kind, text)
    assert normalise_name(kind, text) in str(info.value)


@pytest.mark.parametrize("text", ["", "  ", "\n"])
def test_entity_ref_rejects_a_blank_name(text: str) -> None:
    with pytest.raises(InvariantViolationError, match="canonical_name must not be blank"):
        EntityRef(EntityType.FORM, text)


@pytest.mark.parametrize(
    ("kind", "name", "entity_id", "message"),
    [
        ("form", "GSTR-3B", None, "type must be EntityType"),
        (EntityType.FORM, 3, None, "canonical_name must be str"),
        (EntityType.FORM, "GSTR-3B", ClauseId.new(), "entity_id must be CanonicalEntityId"),
        (EntityType.FORM, "GSTR-3B", EntityId.new(), "entity_id must be CanonicalEntityId"),
        (EntityType.FORM, "GSTR-3B", str(uuid4()), "entity_id must be CanonicalEntityId"),
    ],
)
def test_entity_ref_checks_field_types(
    kind: object, name: object, entity_id: object, message: str
) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        EntityRef(kind, name, entity_id)  # type: ignore[arg-type]


# ---------------------------------------------------------------- Mention


def test_mention_records_where_the_clause_names_the_entity() -> None:
    mention = Mention(CLAUSE, FORM, " FORM GSTR 3B ", 12, 26)
    assert mention.clause_id == CLAUSE
    assert mention.entity == FORM
    assert mention.text == " FORM GSTR 3B "
    assert (mention.span_start, mention.span_end) == (12, 26)
    assert hash(mention) == hash(Mention(CLAUSE, FORM, " FORM GSTR 3B ", 12, 26))
    with pytest.raises(FrozenInstanceError):
        mention.span_end = 30  # type: ignore[misc]
    assert not hasattr(mention, "__dict__")


@given(st.integers(min_value=0, max_value=10_000), st.integers(min_value=0, max_value=10_000))
def test_mention_span_is_a_non_empty_forward_range(start: int, end: int) -> None:
    if start < end:
        mention = Mention(CLAUSE, FORM, "x", start, end)
        assert (mention.span_start, mention.span_end) == (start, end)
    else:
        with pytest.raises(InvariantViolationError, match="span_end must be greater than"):
            Mention(CLAUSE, FORM, "x", start, end)


@pytest.mark.parametrize(
    ("clause_id", "entity", "text", "start", "end", "message"),
    [
        (str(uuid4()), FORM, "x", 0, 1, "clause_id must be ClauseId"),
        (RuleVersionId.new(), FORM, "x", 0, 1, "clause_id must be ClauseId"),
        (CLAUSE, "GSTR-3B", "x", 0, 1, "entity must be EntityRef"),
        (CLAUSE, FORM, "", 0, 1, "text must not be blank"),
        (CLAUSE, FORM, "  ", 0, 1, "text must not be blank"),
        (CLAUSE, FORM, None, 0, 1, "text must be str"),
        (CLAUSE, FORM, "x", -1, 1, "span_start must be at least 0"),
        (CLAUSE, FORM, "x", "0", 1, "span_start must be an integer"),
        (CLAUSE, FORM, "x", False, 1, "span_start must be an integer"),
        (CLAUSE, FORM, "x", 0, 1.5, "span_end must be an integer"),
        (CLAUSE, FORM, "x", 0, True, "span_end must be an integer"),
    ],
)
def test_mention_checks_field_types(
    clause_id: object, entity: object, text: object, start: object, end: object, message: str
) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        Mention(clause_id, entity, text, start, end)  # type: ignore[arg-type]


# ---------------------------------------------------------------- RuleRelation


@pytest.mark.parametrize(("relation", "target_kind", "allowed"), PAIRING_MATRIX)
def test_pairing_matrix(relation: RelationKind, target_kind: str, allowed: bool) -> None:
    target: EntityRef | RuleVersionId = FORM if target_kind == "entity" else OTHER
    if not allowed:
        with pytest.raises(InvalidRelationError, match="must target a rule version") as info:
            RuleRelation(FROM, relation, target, CLAUSE)
        assert relation.value in str(info.value)
        assert "'form'" in str(info.value)
        return
    link = RuleRelation(FROM, relation, target, CLAUSE)
    assert link.target is target
    assert link.to_kind == ("form" if target_kind == "entity" else RULE_VERSION_KIND)
    assert link.to_ref == ("GSTR-3B" if target_kind == "entity" else str(OTHER.value))


def test_pairing_matrix_covers_every_kind_twice() -> None:
    assert sorted(PAIRING_MATRIX) == sorted(
        (kind, target_kind, allowed)
        for kind in RelationKind
        for target_kind, allowed in (
            ("entity", kind not in {RelationKind.SUPERSEDES, RelationKind.EXTENDS_DEADLINE}),
            (RULE_VERSION_KIND, True),
        )
    )


@pytest.mark.parametrize("kind", list(EntityType))
def test_to_kind_is_the_entity_type_value(kind: EntityType) -> None:
    entity = EntityRef(kind, CANONICAL_SAMPLES[kind])
    link = RuleRelation(FROM, RelationKind.REFERS_TO, entity, CLAUSE)
    assert link.to_kind == kind.value
    assert link.to_ref == CANONICAL_SAMPLES[kind]
    assert link.to_kind in {RULE_VERSION_KIND, *(entry.value for entry in EntityType)}


@pytest.mark.parametrize("relation", list(RelationKind))
def test_a_rule_version_cannot_relate_to_itself(relation: RelationKind) -> None:
    same = RuleVersionId(FROM.value)
    with pytest.raises(InvalidRelationError, match="cannot relate to itself") as info:
        RuleRelation(FROM, relation, same, CLAUSE)
    assert relation.value in str(info.value)


def test_rule_relation_is_frozen_and_hashable() -> None:
    link = RuleRelation(FROM, RelationKind.AMENDS, OTHER, CLAUSE)
    assert link == RuleRelation(FROM, RelationKind.AMENDS, RuleVersionId(OTHER.value), CLAUSE)
    assert hash(link) == hash(RuleRelation(FROM, RelationKind.AMENDS, OTHER, CLAUSE))
    assert link != RuleRelation(FROM, RelationKind.REFERS_TO, OTHER, CLAUSE)
    with pytest.raises(FrozenInstanceError):
        link.relation = RelationKind.REFERS_TO  # type: ignore[misc]
    assert not hasattr(link, "__dict__")


@pytest.mark.parametrize(
    ("from_id", "relation", "target", "evidence", "message"),
    [
        (RuleId(FROM.value), RelationKind.AMENDS, OTHER, CLAUSE, "from_rule_version_id must be"),
        (str(FROM), RelationKind.AMENDS, OTHER, CLAUSE, "from_rule_version_id must be"),
        (FROM, "amends", OTHER, CLAUSE, "relation must be RelationKind"),
        (FROM, RelationKind.AMENDS, RuleId(OTHER.value), CLAUSE, "target must be EntityRef or"),
        (FROM, RelationKind.AMENDS, EntityId(OTHER.value), CLAUSE, "target must be EntityRef or"),
        (FROM, RelationKind.AMENDS, "GSTR-3B", CLAUSE, "target must be EntityRef or"),
        (FROM, RelationKind.AMENDS, None, CLAUSE, "target must be EntityRef or"),
        (FROM, RelationKind.AMENDS, OTHER, str(CLAUSE), "evidence_clause_id must be ClauseId"),
        (FROM, RelationKind.AMENDS, OTHER, OTHER, "evidence_clause_id must be ClauseId"),
    ],
)
def test_rule_relation_checks_field_types(
    from_id: object, relation: object, target: object, evidence: object, message: str
) -> None:
    with pytest.raises(InvariantViolationError, match=message):
        RuleRelation(from_id, relation, target, evidence)  # type: ignore[arg-type]


# ---------------------------------------------------------------- InvalidRelationError


def test_invalid_relation_error_is_a_domain_value_error() -> None:
    error = InvalidRelationError()
    assert isinstance(error, DomainError)
    assert isinstance(error, ValueError)
    assert error.type_slug == "invalid-rule-relation"
    assert error.title == "Invalid rule relation"
    assert error.type_uri == PROBLEM_TYPE_PREFIX + "invalid-rule-relation"
    assert str(error) == "Invalid rule relation"
    assert InvalidRelationError("why").detail == "why"
