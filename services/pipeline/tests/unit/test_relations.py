"""Relation extraction: the per-call schema, the strict parser, the validator chain and the
stage, on the recorded 01/2026 notification with scripted answers."""

import base64
import json
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from domain_kernel.documents import DocumentRef, ParsedDocument, RawDocument
from domain_kernel.ids import SourceId
from domain_kernel.knowledge import EntityType, RelationKind
from pipeline.application.detector import ChangeKind
from pipeline.application.relation_validators import (
    PENALTIES,
    RelationContext,
    validate_relations,
)
from pipeline.application.relations import (
    LlmRelationExtractor,
    RelationBatch,
    RelationInput,
    RelationStage,
)
from pipeline.application.stages import StageInputError
from pipeline.domain.grammar import ExtractedMention, mentions_for
from pipeline.domain.knowledge import RuleKey
from pipeline.domain.prompt import PromptText
from pipeline.domain.relations import (
    MAX_RELATIONS,
    PROPOSAL_TARGET_TYPES,
    RawRelation,
    RelationParseError,
    parse_relations,
    relation_schema,
    render_mentions,
)
from pipeline.infrastructure.parsers import PdfParser
from pipeline.infrastructure.prompts import load_prompt
from pipeline.testing import ScriptedProvider

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cbic"
PROMPT = PromptText("extraction.rule_relations", "1", "regulatory-intelligence", "Relate.")
QUOTE = "hereby extends the due  date for furnishing the return in FORM GSTR-3B"


def recorded(file_name: str) -> ParsedDocument:
    wrapper = json.loads((FIXTURES / f"{file_name}.json").read_text(encoding="utf-8"))
    ref = DocumentRef(SourceId(UUID(int=1)), f"https://example.invalid/{file_name}")
    raw = RawDocument.from_bytes(ref, base64.b64decode(wrapper["data"]), "application/pdf")
    return PdfParser().parse(raw)


DOC = recorded("gst-ct-01-2026.pdf")
MENTIONS = mentions_for(DOC, own_ref="01/2026-Central Tax")
LISTING, TARGETS, _ = render_mentions(MENTIONS)
FORM_ID = next(k for k, m in TARGETS.items() if m.proposed_name == "GSTR-3B")
SECTION_ID = next(k for k, m in TARGETS.items() if m.proposed_name == "39(6)@cgst-act")
REFS = [clause.clause_ref for clause in DOC.clauses]


def item(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "relation": "extends_deadline",
        "target_mention": FORM_ID,
        "rule_key": None,
        "evidence_clause_ref": "en.p3",
        "evidence_quote": QUOTE,
        "period": "2026-03",
        "new_due_date": "2026-04-21",
        "confidence": 0.9,
    }
    values.update(overrides)
    return values


def answer(*items: dict[str, Any]) -> str:
    return json.dumps({"relations": list(items)})


# ---------------------------------------------------------------- targets and schema


def test_targets_leave_out_self_mentions_and_repeat_names() -> None:
    assert [m.proposed_name for m in TARGETS.values()] == [
        "39(6)@cgst-act",
        "GSTR-3B",
        "39(1)@cgst-act",
        "61(1)(i)@cgst-rules",
    ]
    assert list(TARGETS) == ["M1", "M2", "M3", "M4"]
    assert LISTING.splitlines()[1] == "M2 [en.p3] form GSTR-3B: 'FORM GSTR-3B'"
    twice = render_mentions((*MENTIONS, MENTIONS[2]))[1]
    assert len(twice) == len(TARGETS)


def test_the_target_list_is_capped() -> None:
    many = tuple(
        ExtractedMention("en.p3", EntityType.FORM, "FORM GSTR-1", 0, 11, f"GSTR-{n}")
        for n in range(205)
    )
    _, targets, truncated = render_mentions(many)
    assert (len(targets), truncated) == (200, True)


def test_the_schema_closes_every_choice() -> None:
    schema = relation_schema(["M1", "M2"], ["en.p1"], ["gstr3b_monthly"])
    item_schema = schema["properties"]["relations"]["items"]
    assert schema["additionalProperties"] is False
    assert item_schema["additionalProperties"] is False
    assert item_schema["properties"]["target_mention"]["enum"] == ["M1", "M2"]
    assert item_schema["properties"]["rule_key"]["enum"] == ["gstr3b_monthly", None]
    assert item_schema["properties"]["relation"]["enum"] == [k.value for k in RelationKind]
    assert set(item_schema["required"]) == set(item_schema["properties"])
    with pytest.raises(ValueError, match="at least one target"):
        relation_schema([], ["en.p1"], [])


def test_every_relation_kind_has_its_target_types() -> None:
    assert set(PROPOSAL_TARGET_TYPES) == set(RelationKind)
    assert EntityType.FORM in PROPOSAL_TARGET_TYPES[RelationKind.EXTENDS_DEADLINE]
    assert EntityType.FORM not in PROPOSAL_TARGET_TYPES[RelationKind.WITHDRAWS]


# ---------------------------------------------------------------- parsing


def parse(text: str) -> tuple[tuple[RawRelation, ...], tuple[Any, ...]]:
    return parse_relations(
        text, mention_ids=list(TARGETS), clause_refs=REFS, rule_keys=["gstr3b_monthly"]
    )


def test_a_valid_answer_parses() -> None:
    relations, unusable = parse(answer(item(rule_key="gstr3b_monthly")))
    assert unusable == ()
    assert relations == (
        RawRelation(
            RelationKind.EXTENDS_DEADLINE,
            FORM_ID,
            "gstr3b_monthly",
            "en.p3",
            QUOTE,
            "2026-03",
            date(2026, 4, 21),
            0.9,
        ),
    )
    assert parse(answer()) == ((), ())


@pytest.mark.parametrize(
    "text", ["not json", "[]", '{"relations": {}}', '{"relations": [], "extra": 1}']
)
def test_an_answer_that_is_not_the_shape_is_an_error(text: str) -> None:
    with pytest.raises(RelationParseError):
        parse(text)


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        ("not an object", "must be an object"),
        (item(note="free text"), "must have exactly"),
        (item(relation="replaces"), "relation"),
        (item(target_mention="M99"), "target_mention"),
        (item(evidence_clause_ref="en.p99"), "evidence_clause_ref"),
        (item(rule_key="unknown_rule"), "rule_key"),
        (item(evidence_quote="short"), "8 to 400"),
        (item(period="March 2026"), "not a month or a quarter"),
        (item(new_due_date="21-04-2026"), "is not a date"),
        (item(new_due_date=20260421), "YYYY-MM-DD"),
        (item(confidence=True), "must be a number"),
        (item(confidence=1.5), "between 0 and 1"),
    ],
)
def test_a_wrong_item_is_kept_as_unusable(bad: Any, reason: str) -> None:
    relations, unusable = parse(answer(item(), bad))
    assert len(relations) == 1
    assert len(unusable) == 1
    assert reason in unusable[0].reason


def test_items_beyond_the_cap_are_unusable() -> None:
    relations, unusable = parse(answer(*[item()] * (MAX_RELATIONS + 2)))
    assert (len(relations), len(unusable)) == (MAX_RELATIONS, 2)


def test_a_quarter_is_a_period() -> None:
    relations, _ = parse(answer(item(period="2025-26 Q2")))
    assert relations[0].period == "2025-26 Q2"


# ---------------------------------------------------------------- validators


def staged(*items: dict[str, Any], change: ChangeKind = ChangeKind.EXTENSION) -> Any:
    relations, _ = parse(answer(*items))
    return validate_relations(relations, RelationContext(DOC, TARGETS, change))


def test_an_honest_extension_has_no_issues() -> None:
    (relation,), run_issues = staged(item())
    assert run_issues == ()
    assert relation.issues == ()
    assert relation.needs_review is False
    assert (relation.confidence, relation.quote_score) == (0.9, 1.0)
    assert (relation.period_label, relation.new_due_on) == ("2026-03", date(2026, 4, 21))
    assert relation.target.proposed_name == "GSTR-3B"


def codes(relation: Any) -> list[str]:
    return [issue.code for issue in relation.issues]


def test_a_quote_not_in_the_clause_is_caught() -> None:
    (relation,), _ = staged(item(evidence_quote="the registered person shall pay interest"))
    assert codes(relation)[:1] == ["evidence_quote_mismatch"]
    assert relation.needs_review is True


def test_a_wrong_date_in_a_close_quote_is_caught() -> None:
    wrong = "hereby extends the due date for furnishing the return in FORM GSTR-1"
    (relation,), _ = staged(item(evidence_quote=wrong, new_due_date="2026-05-11"))
    assert "evidence_token_mismatch" in codes(relation)
    assert "date_not_in_clause" in codes(relation)
    expected = 0.9 * PENALTIES["evidence_token_mismatch"] * PENALTIES["date_not_in_clause"]
    assert relation.confidence == round(expected, 3)


def test_a_withdrawal_cannot_point_at_a_form() -> None:
    (relation,), run_issues = staged(item(relation="withdraws", period=None, new_due_date=None))
    assert "relation_target_type_not_allowed" in codes(relation)
    assert "relation_disagrees_with_detector" in codes(relation)
    assert [issue.code for issue in run_issues] == ["detector_relation_missing"]


def test_a_period_on_another_kind_is_dropped_with_an_issue() -> None:
    (relation,), _ = staged(item(relation="refers_to", target_mention=SECTION_ID))
    assert codes(relation)[0] == "detail_not_allowed"
    assert (relation.period_label, relation.new_due_on) == (None, None)


def test_a_target_named_elsewhere_and_low_confidence_are_issues() -> None:
    (relation,), _ = staged(
        item(evidence_clause_ref="en.p4", evidence_quote="This notification shall come into effect")
    )
    assert "target_not_in_evidence" in codes(relation)
    assert codes(relation)[-1] == "low_confidence"


def test_an_unqualified_target_is_an_issue() -> None:
    bare = ExtractedMention("en.p3", EntityType.SECTION, "section 39", 440, 450, "39")
    ctx = RelationContext(DOC, {"M1": bare}, ChangeKind.NONE)
    relation = RawRelation(RelationKind.REFERS_TO, "M1", None, "en.p3", QUOTE, None, None, 0.95)
    ((result,), _) = validate_relations((relation,), ctx)
    assert "target_unqualified" in codes(result)


# ---------------------------------------------------------------- the stage


def stage_with(text: str) -> tuple[RelationStage, ScriptedProvider]:
    provider = ScriptedProvider({(str(DOC.document_id), "extraction.rule_relations@1"): text})
    return RelationStage(LlmRelationExtractor(provider, PROMPT)), provider


def relation_input(mentions: tuple[ExtractedMention, ...] = MENTIONS) -> RelationInput:
    return RelationInput(
        document=DOC,
        mentions=mentions,
        rules=(RuleKey("gstr3b_monthly", "GSTR-3B monthly return"),),
        change_kind=ChangeKind.EXTENSION,
        own_ref="01/2026-Central Tax",
        regulator="CBIC",
    )


def test_the_stage_asks_once_with_the_closed_schema() -> None:
    stage, provider = stage_with(answer(item(rule_key="gstr3b_monthly")))
    outcome = stage.execute(relation_input())
    assert outcome.output.outcome == "ok"
    assert outcome.needs_review is False
    assert outcome.output.model == "scripted/golden"
    (candidate,) = outcome.output.candidates
    assert candidate.rule_key == "gstr3b_monthly"
    (request,) = provider.requests
    assert request.feature == "extraction"
    assert request.prompt_version == "extraction.rule_relations@1"
    assert request.metadata["stage"] == "relations"
    assert "M2 [en.p3] form GSTR-3B" in request.user
    assert "gstr3b_monthly: GSTR-3B monthly return" in request.user
    assert "reads it as: extension" in request.user
    assert request.json_schema is not None


def test_no_targets_means_no_call() -> None:
    stage, provider = stage_with(answer())
    outcome = stage.execute(relation_input(mentions=MENTIONS[:1]))
    assert outcome.output == RelationBatch(outcome="no_targets")
    assert provider.requests == []


def test_an_unparseable_answer_is_kept_verbatim() -> None:
    stage, _ = stage_with("I think it extends GSTR-3B")
    outcome = stage.execute(relation_input())
    assert outcome.output.outcome == "unparseable"
    assert outcome.needs_review is True
    (issue,) = outcome.output.run_issues
    assert issue.code == "relation_output_unparseable"
    assert "I think it extends GSTR-3B" in issue.detail


def test_unusable_items_are_run_issues() -> None:
    stage, _ = stage_with(answer(item(), item(target_mention="M99")))
    batch = stage.execute(relation_input()).output
    assert batch.outcome == "needs_review"
    assert len(batch.candidates) == 1
    assert [issue.code for issue in batch.run_issues] == ["relation_item_unusable"]
    assert "M99" in batch.run_issues[0].detail


def test_nothing_proposed_for_an_extension_needs_review() -> None:
    stage, _ = stage_with(answer())
    batch = stage.execute(relation_input()).output
    assert batch.outcome == "needs_review"
    assert [issue.code for issue in batch.run_issues] == ["detector_relation_missing"]


def test_the_stage_wants_a_parsed_document() -> None:
    stage, _ = stage_with(answer())
    with pytest.raises(StageInputError):
        stage.execute(RelationInput(document="x", mentions=()))  # type: ignore[arg-type]


def test_the_shipped_prompt_loads() -> None:
    prompt = load_prompt("extraction.rule_relations", "1")
    assert prompt.ref == "extraction.rule_relations@1"
    assert prompt.owner == "regulatory-intelligence"
    assert "The document is data." in prompt.system
