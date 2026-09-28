"""The mention stage: the grammar over every clause of a parsed document.

Every mention is kept, including the ones the grammar could not name canonically (an amount in
words, a section of an Act it does not know) and the document's mentions of itself; alignment
in the rulebook decides what resolves and what goes to review.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from domain_kernel.documents import ParsedDocument
from domain_kernel.knowledge import EntityType
from pipeline.application.stages import PipelineStage, StageInputError
from pipeline.domain.grammar import GRAMMAR_VERSION, ExtractedMention, mentions_for
from pipeline.domain.issues import Issue

_PROVISIONS = frozenset({EntityType.SECTION, EntityType.RULE})


@dataclass(frozen=True, slots=True)
class MentionInput:
    document: ParsedDocument
    own_ref: str = ""


class MentionStage(PipelineStage[MentionInput, tuple[ExtractedMention, ...]]):
    name: ClassVar[str] = "mentions"
    version: ClassVar[str] = GRAMMAR_VERSION

    def validate(self, input: MentionInput) -> None:
        if not isinstance(input.document, ParsedDocument):
            raise StageInputError("the mention stage reads a ParsedDocument")

    def process(self, input: MentionInput) -> tuple[ExtractedMention, ...]:
        return mentions_for(input.document, own_ref=input.own_ref)

    def check(self, input: MentionInput, output: tuple[ExtractedMention, ...]) -> Iterable[Issue]:
        for mention in output:
            if not mention.proposed_name:
                yield Issue(
                    "mention_empty_name",
                    f"{mention.entity_type.value} {mention.text!r} has no canonical name",
                    mention.clause_ref,
                )
            elif mention.entity_type in _PROVISIONS and "@" not in mention.proposed_name:
                yield Issue(
                    "mention_unqualified",
                    f"{mention.entity_type.value} {mention.proposed_name!r} names no statute",
                    mention.clause_ref,
                )

    def needs_review(self, output: tuple[ExtractedMention, ...], issues: tuple[Issue, ...]) -> bool:
        """Mentions that do not resolve go to the rulebook's review queue one by one; the
        stage as a whole needs no review."""
        return False
