"""``eval-golden-check``: the KAG golden set and its world, checked without running a service.

It reads ``evals/golden/qa/kag``: the world file and every case. It checks the keys and the
closed values, the label status rules (a draft has ``labelled_by`` and no ``reviewed_by``; an
approved case has a ``reviewed_by`` other than ``labelled_by``), that every key names something
in the world and a notification version carries its CBIC listing title, that every quote is in
its clause word for word (whitespace aside), that a fact holds in its own support (a date is
among the dates its quote writes, ordinal words included, and a text is in its quote, casefolded
and dashes folded), that every seed-calendar support matches the seed file, that the scripted
plans pass qa's plan rules against the rules the world has in force on the case's date (a first
plan with a ``plan_retry`` must fail them, or the retry is never asked for) and the scripted
answers qa's answer shape, that an answerable case's scripted citations are among its
expected ones, and that a must-refuse case's scripted answer is bad on purpose: covered, with
at least one citation the check must reject, and without stating a date or an amount. It prints
the count per category and per status, and exits 1 on any problem.
"""

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final

from cw_evals.cases import DEFAULT_GOLDEN
from cw_evals.qa.cases import (
    CASE_ID,
    CASES_DIR,
    CATEGORIES,
    FACT_KINDS,
    FACT_SOURCES,
    LABEL_STATUSES,
    OUTCOMES,
    CaseError,
    ClauseSupport,
    QaCase,
    SeedSupport,
    load_qa_case,
    planner_json,
    scripted_answer,
)
from cw_evals.qa.score import dates_in, folded, has_amount
from cw_evals.qa.world import ClauseQuote, WorldError, WorldSpec, load_world
from domain_kernel.predicates import specification_to_mapping
from qa.domain.answer import AnswerInvalidError, parse_answer
from qa.domain.intents import match_intent
from qa.domain.plan_schema import PlanContext, PlanInvalidError, plan_from_mapping

_LABEL: Final = re.compile(r"C[0-9]+")


def normalised(text: str) -> str:
    return " ".join(text.split())


def quote_in(quote: str, clause: str | None) -> bool:
    """Whether ``quote`` is in ``clause`` word for word, whitespace aside."""
    return clause is not None and normalised(quote) in normalised(clause)


def seed_value(spec: WorldSpec, rule_key: str, field: str) -> object:
    """A seed rule's field by dotted path, in the seed file's own shapes."""
    rule = spec.seed.get(rule_key)
    if rule is None:
        raise KeyError(f"no seed rule {rule_key!r}")
    value: object = {
        "title": rule.title,
        "effective_from": rule.effective_from.isoformat(),
        "specification": specification_to_mapping(rule.specification),
        "obligation_template": rule.obligation_template.to_mapping(),
        "recurrence": None if rule.recurrence is None else rule.recurrence.to_mapping(),
    }
    for part in field.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(f"seed rule {rule_key!r} has no {field!r}")
        value = value[part]
    return value


def check_world(spec: WorldSpec) -> list[str]:
    problems = _status("world.yaml", spec.label_status, spec.labelled_by, spec.reviewed_by)
    for document in spec.documents:
        problems += _quote("world.yaml", document.published_on_support, spec)
    for rule in spec.rules:
        if not rule.citations:
            problems.append(f"world.yaml: {rule.rule_key} cites no clause")
            continue
        listing = str(spec.cases[rule.citations[0].document].source.get("title", ""))
        if not rule.seed and not (listing and rule.title.endswith(listing)):
            problems.append(
                f"world.yaml: {rule.rule_key} is titled with its notification's listing title"
            )
        for citation in rule.citations:
            problems += _quote("world.yaml", citation, spec)
        if rule.effective_from_support is not None:
            problems += _quote("world.yaml", rule.effective_from_support, spec)
    return problems


def check_case(case: QaCase, spec: WorldSpec) -> list[str]:
    where = case.path.name
    problems: list[str] = []
    if not CASE_ID.fullmatch(case.case_id) or case.path.stem != case.case_id:
        problems.append(f"{where}: case_id {case.case_id!r} must match the file name")
    for name, value, allowed in (
        ("category", case.category, CATEGORIES),
        ("fact_source", case.fact_source, FACT_SOURCES),
        ("expected.outcome", case.expected.outcome, OUTCOMES),
        ("label_status", case.label_status, LABEL_STATUSES),
    ):
        if value not in allowed:
            problems.append(f"{where}: {name} {value!r} is not one of {', '.join(allowed)}")
    problems += _status(where, case.label_status, case.labelled_by, case.reviewed_by)
    if case.business is not None and case.business not in {b.key for b in spec.businesses}:
        problems.append(f"{where}: business {case.business!r} is not in the world")
    must_refuse = case.category == "must_refuse"
    if must_refuse != (case.expected.outcome == "not_covered"):
        problems.append(f"{where}: must_refuse cases, and only they, expect not_covered")
    problems += _facts(case, spec)
    for citation in case.expected.citations:
        if spec.clause_text(citation.document, citation.clause_ref) is None:
            problems.append(f"{where}: {citation.document} has no clause {citation.clause_ref}")
    problems += _scripted(case, spec)
    if must_refuse:
        problems += _refusal(case, spec)
    elif not case.expected.citations:
        problems.append(f"{where}: an answerable case expects at least one citation")
    return problems


def _facts(case: QaCase, spec: WorldSpec) -> list[str]:
    where = case.path.name
    problems: list[str] = []
    for fact in case.expected.facts:
        if fact.kind not in FACT_KINDS:
            problems.append(f"{where}: fact kind {fact.kind!r} is not one of {FACT_KINDS}")
        day: date | None = None
        if fact.kind == "date":
            try:
                day = date.fromisoformat(fact.value)
            except ValueError:
                problems.append(f"{where}: fact {fact.value!r} is not an ISO date")
        support = fact.support
        if isinstance(support, SeedSupport):
            try:
                found = seed_value(spec, support.seed_rule, support.field)
            except KeyError as exc:
                problems.append(f"{where}: {exc.args[0]}")
                continue
            if found != support.value:
                problems.append(
                    f"{where}: seed {support.seed_rule}.{support.field} is {found!r}, "
                    f"not {support.value!r}"
                )
        else:
            problems += _quote(where, support, spec)
            if day is not None and day not in dates_in(support.quote):
                problems.append(f"{where}: date {fact.value} is not in its quote {support.quote!r}")
            if fact.kind == "text" and folded(fact.value) not in folded(support.quote):
                problems.append(f"{where}: {fact.value!r} is not in its quote {support.quote!r}")
    return problems


def _scripted(case: QaCase, spec: WorldSpec) -> list[str]:
    where = case.path.name
    problems: list[str] = []
    scripted = case.scripted
    structured = case.business is not None and match_intent(case.question, case.as_of) is not None
    if not structured and scripted.plan is None:
        problems.append(f"{where}: a question past the structured layer needs scripted.plan")
    if not structured and scripted.answer is None and case.category == "must_refuse":
        problems.append(f"{where}: a must-refuse case scripts its (bad) answer")
    context = PlanContext(
        as_of=case.as_of,
        has_business=case.business is not None,
        rule_keys=spec.rules_in_force(case.as_of),
        regulators=frozenset({"cbic"}),
    )
    for name, plan in (("plan", scripted.plan), ("plan_retry", scripted.plan_retry)):
        if plan is None:
            continue
        try:
            plan_from_mapping(planner_json(plan), context)
        except PlanInvalidError as exc:
            if not (name == "plan" and scripted.plan_retry is not None):
                problems.append(f"{where}: scripted.{name} is not a valid plan: {exc}")
            continue
        if name == "plan" and scripted.plan_retry is not None:
            problems.append(f"{where}: scripted.plan is valid, so plan_retry is never asked")
    answer = scripted.answer
    if answer is None:
        return problems
    try:
        text = json.dumps(scripted_answer(answer, _numbered(answer, spec), _sources(spec)))
        parse_answer(text)
    except (AnswerInvalidError, KeyError, TypeError) as exc:
        problems.append(f"{where}: scripted.answer is not an answer: {exc}")
        return problems
    if case.category != "must_refuse":
        expected = {(c.document, c.clause_ref) for c in case.expected.citations}
        if answer.get("covered") is not True:
            problems.append(f"{where}: the scripted answer of an answerable case covers it")
        for item in answer.get("citations") or []:
            if "clause" in item:
                problems.append(f"{where}: an answerable case cites by document and clause_ref")
                continue
            key = (str(item["document"]), str(item["clause_ref"]))
            if key not in expected:
                problems.append(f"{where}: scripted citation {key} is not an expected citation")
            if not quote_in(str(item["quote"]), spec.clause_text(*key)):
                problems.append(f"{where}: scripted quote is not in {key[0]} {key[1]}")
    return problems


def _refusal(case: QaCase, spec: WorldSpec) -> list[str]:
    """A must-refuse answer is bad on purpose: it claims to cover the question with at least one
    citation, so the citation check (not the model declining) is what refuses it; each citation
    names a label, a quote its clause lacks, or a clause of a document not yet published on the
    question's date; and it states no date and no amount."""
    where = case.path.name
    problems: list[str] = []
    if case.expected.facts or case.expected.citations:
        problems.append(f"{where}: a must-refuse case expects no facts and no citations")
    if not case.refusal_reason:
        problems.append(f"{where}: a must-refuse case names its refusal_reason")
    answer = case.scripted.answer or {}
    if case.scripted.answer is not None and (
        answer.get("covered") is not True or not answer.get("citations")
    ):
        problems.append(
            f"{where}: a must-refuse case scripts covered: true with at least one citation"
        )
    texts = [str(answer.get("answer", ""))]
    for item in answer.get("citations") or []:
        texts.append(str(item.get("quote", "")))
        if "clause" in item:
            if not _LABEL.fullmatch(str(item["clause"])):
                problems.append(f"{where}: a label looks like C13, got {item['clause']!r}")
            continue
        document, clause_ref = str(item["document"]), str(item["clause_ref"])
        published = spec.document(document).published_on
        if quote_in(str(item["quote"]), spec.clause_text(document, clause_ref)) and (
            published <= case.as_of
        ):
            problems.append(f"{where}: the scripted answer cites a quote that holds")
    for text in texts:
        if dates_in(text) or has_amount(text):
            problems.append(f"{where}: a must-refuse answer states no date or amount: {text!r}")
    return problems


def _numbered(answer: Mapping[str, Any], spec: WorldSpec) -> str:
    """Evidence headings giving each clause the answer cites a label, as a prompt would."""
    lines = []
    for number, item in enumerate(answer.get("citations") or [], start=1):
        if "document" in item:
            source = spec.document(str(item["document"])).own_ref
            lines.append(f"[C{number}] {item['clause_ref']} ({source})")
    return "\n".join(lines)


def _sources(spec: WorldSpec) -> dict[str, str]:
    return {document.key: document.own_ref for document in spec.documents}


def _quote(where: str, support: ClauseSupport | ClauseQuote, spec: WorldSpec) -> list[str]:
    text = spec.clause_text(support.document, support.clause_ref)
    if text is None:
        return [f"{where}: {support.document} has no clause {support.clause_ref}"]
    if not quote_in(support.quote, text):
        return [f"{where}: {support.quote!r} is not in {support.document} {support.clause_ref}"]
    return []


def _status(where: str, status: str, labelled_by: str, reviewed_by: str) -> list[str]:
    if status == "draft" and (not labelled_by or reviewed_by):
        return [f"{where}: a draft has labelled_by and an empty reviewed_by"]
    if status == "reviewed" and not labelled_by:
        return [f"{where}: a reviewed label names labelled_by"]
    if status == "approved" and (not reviewed_by or reviewed_by == labelled_by):
        return [f"{where}: an approved label names a reviewed_by other than labelled_by"]
    return []


def check(golden: Path) -> tuple[list[str], list[QaCase]]:
    """Every problem with the world and the cases under ``golden``, and the cases read."""
    try:
        spec = load_world(golden)
    except (WorldError, OSError) as exc:
        return [f"world.yaml: {exc}"], []
    problems = check_world(spec)
    cases: list[QaCase] = []
    for path in sorted((golden / CASES_DIR).glob("*.yaml")):
        try:
            cases.append(load_qa_case(path))
        except CaseError as exc:
            problems.append(str(exc))
    for case in cases:
        problems += check_case(case, spec)
    for case_id, count in Counter(case.case_id for case in cases).items():
        if count > 1:
            problems.append(f"case_id {case_id} is used {count} times")
    return problems, cases


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eval-golden-check", description=__doc__)
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    args = parser.parse_args(argv)
    problems, cases = check(args.golden)
    for problem in problems:
        sys.stdout.write(f"problem: {problem}\n")
    categories = Counter(case.category for case in cases)
    statuses = Counter(case.label_status for case in cases)
    sys.stdout.write(
        f"{args.golden / CASES_DIR}: {len(cases)} cases "
        f"({', '.join(f'{name} {categories.get(name, 0)}' for name in CATEGORIES)}; "
        f"{', '.join(f'{name} {statuses.get(name, 0)}' for name in LABEL_STATUSES)}), "
        f"{len(problems)} problems\n"
    )
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
