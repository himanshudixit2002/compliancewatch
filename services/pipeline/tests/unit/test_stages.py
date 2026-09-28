"""The stage template and the mention stage."""

import base64
import json
from collections.abc import Iterable
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import ClassVar
from uuid import UUID

import pytest

from domain_kernel.documents import DocumentRef, ParsedDocument, RawDocument
from domain_kernel.ids import SourceId
from pipeline.application.mentions import MentionInput, MentionStage
from pipeline.application.stages import PipelineStage, StageInputError, StageOutcome
from pipeline.domain.grammar import mentions_for
from pipeline.domain.issues import Issue
from pipeline.infrastructure.parsers import PdfParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cbic"


def recorded(file_name: str) -> ParsedDocument:
    wrapper = json.loads((FIXTURES / f"{file_name}.json").read_text(encoding="utf-8"))
    ref = DocumentRef(SourceId(UUID(int=1)), f"https://example.invalid/{file_name}")
    raw = RawDocument.from_bytes(ref, base64.b64decode(wrapper["data"]), "application/pdf")
    return PdfParser().parse(raw)


class Doubler(PipelineStage[int, int]):
    name: ClassVar[str] = "doubler"
    version: ClassVar[str] = "doubler@1"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def validate(self, input: int) -> None:
        self.calls.append("validate")
        if input < 0:
            raise StageInputError("negative")

    def process(self, input: int) -> int:
        self.calls.append("process")
        return input * 2

    def check(self, input: int, output: int) -> Iterable[Issue]:
        self.calls.append("check")
        if output > 10:
            yield Issue("too_big", f"{output} > 10")


class Plain(PipelineStage[str, str]):
    name: ClassVar[str] = "plain"
    version: ClassVar[str] = "plain@1"

    def process(self, input: str) -> str:
        return input.upper()


def test_execute_runs_validate_process_check_in_order() -> None:
    stage = Doubler()
    outcome = stage.execute(3)
    assert stage.calls == ["validate", "process", "check"]
    assert outcome == StageOutcome(6, (), needs_review=False)


def test_issues_mean_review_by_default() -> None:
    outcome = Doubler().execute(7)
    assert outcome.output == 14
    assert outcome.issues == (Issue("too_big", "14 > 10"),)
    assert outcome.needs_review is True


def test_a_bad_input_stops_before_any_work() -> None:
    stage = Doubler()
    with pytest.raises(StageInputError, match="negative"):
        stage.execute(-1)
    assert stage.calls == ["validate"]


def test_the_hooks_default_to_nothing() -> None:
    outcome = Plain().execute("gstr")
    assert outcome == StageOutcome("GSTR")
    with pytest.raises(FrozenInstanceError):
        outcome.output = "x"  # type: ignore[misc]


def test_the_mention_stage_is_the_grammar_over_the_document() -> None:
    doc = recorded("gst-ct-01-2026.pdf")
    outcome = MentionStage().execute(MentionInput(doc, own_ref="01/2026-Central Tax"))
    assert outcome.output == mentions_for(doc, own_ref="01/2026-Central Tax")
    assert len(outcome.output) == 5
    assert outcome.issues == ()
    assert MentionStage.version == "grammar@1"


def test_unqualified_and_unnamed_mentions_are_issues_not_review() -> None:
    doc = recorded("gst-ct-10-2025.pdf")
    outcome = MentionStage().execute(MentionInput(doc, own_ref="10/2025-Central Tax"))
    assert [(issue.code, issue.clause_ref) for issue in outcome.issues] == [
        ("mention_unqualified", "en.p1")
    ]
    assert outcome.needs_review is False


def test_the_mention_stage_wants_a_parsed_document() -> None:
    with pytest.raises(StageInputError, match="ParsedDocument"):
        MentionStage().execute(MentionInput("not a document"))  # type: ignore[arg-type]
