"""The answerer: one ``qa.answer@1`` call that phrases the answer from an evidence bundle.

The schema lets a citation name only the bundle's clause labels. The answer is then read and
every quote checked against its clause (``check_citations``); an answer that fails gets one
retry that lists the problems, and a second failure is ``not_covered``
(``citation_check_failed``). A model that says the evidence does not cover the question gives
``not_covered`` (``answerer_declined``). A gateway failure is ``DependencyUnavailableError``:
the question cannot be answered or refused honestly without the model.
"""

from typing import Final

from domain_kernel.llm import CompletionRequest
from domain_kernel.protocols import LLMProvider
from qa.application.context import AskContext, AskRequest
from qa.domain.answer import (
    Answer,
    AnswerInvalidError,
    Layer,
    Reason,
    answer_schema,
    check_citations,
    cite,
    parse_answer,
)
from qa.domain.errors import DependencyUnavailableError, GatewayError
from qa.domain.evidence import EvidenceBundle, render_bundle
from qa.domain.prompt import PromptText

FEATURE: Final = "qa"
ANSWER_MAX_TOKENS: Final = 1_500
STAGE: Final = "answer"


class Answerer:
    def __init__(self, provider: LLMProvider, prompt: PromptText) -> None:
        self._provider = provider
        self._prompt = prompt

    @property
    def prompt_ref(self) -> str:
        return self._prompt.ref

    def answer(self, ctx: AskContext, bundle: EvidenceBundle, layer: Layer) -> Answer:
        """The answer from a bundle with at least one clause."""
        schema = answer_schema(bundle.labels)
        user = render_evidence(ctx.request, bundle)
        problems: tuple[str, ...] = ()
        for attempt in (1, 2):
            text = user
            if problems:
                text += (
                    "\n\nYour previous answer failed the check: "
                    + "; ".join(problems)
                    + ". Cite only the clauses above, with quotes copied exactly from them."
                )
            try:
                response = self._provider.complete(
                    CompletionRequest(
                        feature=FEATURE,
                        prompt_version=self._prompt.ref,
                        system=self._prompt.system,
                        user=text,
                        max_tokens=ANSWER_MAX_TOKENS,
                        json_schema=schema,
                        tenant_id=ctx.request.tenant,
                        metadata=ctx.metadata(STAGE, attempt, layer),
                    )
                )
            except GatewayError as exc:
                raise DependencyUnavailableError(f"llm-gateway: {exc}") from exc
            try:
                draft = parse_answer(response.text)
            except AnswerInvalidError as exc:
                problems = exc.problems
                continue
            if not draft.covered:
                return Answer.not_covered(Reason.ANSWERER_DECLINED)
            problems = check_citations(draft, bundle)
            if not problems:
                return Answer.answered(draft.answer.strip(), cite(draft, bundle))
        return Answer.not_covered(Reason.CITATION_CHECK_FAILED)


def render_evidence(request: AskRequest, bundle: EvidenceBundle) -> str:
    """What the answerer reads: the question, its date, then the labelled evidence."""
    return "\n".join(
        [
            f"Question: {request.question}",
            f"Date of the question: {request.as_of.isoformat()}",
            "",
            render_bundle(bundle),
        ]
    )
