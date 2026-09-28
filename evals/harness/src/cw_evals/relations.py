"""The relation suite: golden relation cases, how a provider does on them, and the scores.

A relation case points at an extraction case for its document (the clauses as parsed) and lists
the relations an analyst expects the document to state, each with its target by type and
canonical name and the clause that states it. The run puts the document through the mention
grammar and the relation stage exactly as the pipeline does, then compares the candidates with
the expected relations on (relation, target type, target name).

``scripted`` answers each case with its own label, which proves the scoring and the validators
end to end; ``fake`` exercises the plumbing through the in-process gateway (it answers an empty
list by design); ``gateway`` reaches a real model in the nightly run.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from cw_evals.providers import fake_gateway, http_gateway
from domain_kernel.documents import DocumentType, ParsedDocument
from domain_kernel.knowledge import EntityType, RelationKind
from domain_kernel.protocols import LLMProvider
from pipeline.application.detector import detect
from pipeline.application.relations import (
    LlmRelationExtractor,
    RelationBatch,
    RelationInput,
    RelationStage,
)
from pipeline.domain.grammar import mentions_for
from pipeline.domain.relations import render_mentions
from pipeline.infrastructure.prompts import load_prompt
from pipeline.label import load_case
from pipeline.testing import ScriptedProvider

PROMPT = ("extraction.rule_relations", "1")
EVIDENCE_CODES = frozenset({"evidence_quote_mismatch", "evidence_token_mismatch"})


@dataclass(frozen=True, slots=True)
class ExpectedRelation:
    relation: RelationKind
    target_type: EntityType
    target_name: str
    evidence_clause_ref: str
    evidence_quote: str
    period: str | None = None
    new_due_date: date | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.relation.value, self.target_type.value, self.target_name)


@dataclass(frozen=True, slots=True)
class RelationCase:
    case_id: str
    label_status: str
    own_ref: str
    document: ParsedDocument
    expected: tuple[ExpectedRelation, ...]


@dataclass(frozen=True, slots=True)
class RelationScore:
    case_id: str
    label_status: str
    outcome: str
    expected: int
    found: int
    proposed: int
    evidence_ok: int
    missed: tuple[str, ...] = ()
    candidates: int = 0
    """Candidates the run staged, counted one by one (``proposed`` counts distinct targets)."""


@dataclass(frozen=True, slots=True)
class RelationAggregate:
    cases: int
    relation_parse_rate: float
    relation_recall: float
    relation_precision: float
    evidence_validity: float


def load_relation_cases(golden: Path) -> list[RelationCase]:
    root = golden / "relations"
    cases: list[RelationCase] = []
    for path in sorted(root.rglob("cases/*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        extraction = load_case(golden / str(data["extraction_case"]))
        cases.append(
            RelationCase(
                case_id=str(data["case_id"]),
                label_status=str(data["label_status"]),
                own_ref=str(data["own_ref"]),
                document=extraction.document,
                expected=tuple(_expected(item) for item in data["expected"]["relations"]),
            )
        )
    return cases


def _expected(item: Mapping[str, Any]) -> ExpectedRelation:
    due = item.get("new_due_date")
    return ExpectedRelation(
        relation=RelationKind(item["relation"]),
        target_type=EntityType(item["target"]["type"]),
        target_name=str(item["target"]["name"]),
        evidence_clause_ref=str(item["evidence_clause_ref"]),
        evidence_quote=str(item["evidence_quote"]),
        period=item.get("period"),
        new_due_date=None if due is None else date.fromisoformat(str(due)),
    )


def relation_input(case: RelationCase) -> RelationInput:
    detection = detect(case.document, default_type=DocumentType.NOTIFICATION, own_ref=case.own_ref)
    return RelationInput(
        document=case.document,
        mentions=mentions_for(case.document, own_ref=case.own_ref),
        change_kind=detection.change_kind,
        own_ref=case.own_ref,
        regulator="CBIC",
    )


def scripted_answer(case: RelationCase) -> str:
    """The case's label written as the model's answer, targets named by their mention ids."""
    _, targets, _ = render_mentions(relation_input(case).mentions)
    by_key = {
        (m.entity_type.value, m.proposed_name): mention_id for mention_id, m in targets.items()
    }
    relations = []
    for expected in case.expected:
        relations.append(
            {
                "relation": expected.relation.value,
                "target_mention": by_key[(expected.target_type.value, expected.target_name)],
                "rule_key": None,
                "evidence_clause_ref": expected.evidence_clause_ref,
                "evidence_quote": expected.evidence_quote,
                "period": expected.period,
                "new_due_date": None
                if expected.new_due_date is None
                else expected.new_due_date.isoformat(),
                "confidence": 1.0,
            }
        )
    return json.dumps({"relations": relations})


@contextmanager
def relation_provider(
    name: str, cases: Sequence[RelationCase], *, gateway_url: str
) -> Iterator[LLMProvider]:
    if name == "scripted":
        ref = "{}@{}".format(*PROMPT)
        yield ScriptedProvider(
            {(str(case.document.document_id), ref): scripted_answer(case) for case in cases}
        )
    elif name == "fake":
        with fake_gateway() as provider:
            yield provider
    elif name == "gateway":
        with http_gateway(gateway_url) as provider:
            yield provider
    else:
        raise ValueError(f"unknown provider {name!r}")


def score_relations(case: RelationCase, batch: RelationBatch) -> RelationScore:
    proposed = {
        (c.relation.value, c.target.entity_type.value, c.target.proposed_name)
        for c in batch.candidates
    }
    expected = {e.key for e in case.expected}
    evidence_ok = sum(
        1 for c in batch.candidates if not EVIDENCE_CODES & {i.code for i in c.issues}
    )
    return RelationScore(
        case_id=case.case_id,
        label_status=case.label_status,
        outcome=batch.outcome,
        expected=len(expected),
        found=len(expected & proposed),
        proposed=len(proposed),
        evidence_ok=evidence_ok,
        missed=tuple(sorted("/".join(key) for key in expected - proposed)),
        candidates=len(batch.candidates),
    )


def aggregate_relations(scores: Sequence[RelationScore]) -> RelationAggregate:
    cases = len(scores)
    expected = sum(s.expected for s in scores)
    proposed = sum(s.proposed for s in scores)
    return RelationAggregate(
        cases=cases,
        relation_parse_rate=_share(sum(s.outcome != "unparseable" for s in scores), cases),
        relation_recall=_share(sum(s.found for s in scores), expected),
        relation_precision=_share(sum(s.found for s in scores), proposed, empty=1.0),
        evidence_validity=_share(
            sum(s.evidence_ok for s in scores), sum(s.candidates for s in scores), empty=1.0
        ),
    )


def _share(part: int, whole: int, *, empty: float = 0.0) -> float:
    return part / whole if whole else empty


def run_relations(
    cases: Sequence[RelationCase], provider_name: str, *, gateway_url: str
) -> tuple[RelationAggregate, list[RelationScore]]:
    prompt = load_prompt(*PROMPT)
    scores: list[RelationScore] = []
    with relation_provider(provider_name, cases, gateway_url=gateway_url) as provider:
        stage = RelationStage(LlmRelationExtractor(provider, prompt))
        for case in cases:
            scores.append(score_relations(case, stage.execute(relation_input(case)).output))
    return aggregate_relations(scores), scores
