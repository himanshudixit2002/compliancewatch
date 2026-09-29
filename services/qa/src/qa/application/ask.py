"""Answer a question in layers, cheapest first, stopping at the first that decides (ADR-012).

1. Structured: two phrasings answered from the business's obligations, no model call.
2. KAG (only when the flag is on for the tenant): plan, solve, answer (ADR-017).
3. Hybrid: search clauses and answer from the hits.

Every layer that ran is recorded as ``{layer, result, reason}``; the result names the deciding
layer and carries the plan whenever one validated, even when a later layer answered. There is
no fourth, agentic layer and no reranker. Spans: ``qa.ask`` around the question and
``qa.layer`` around each layer, with ids, codes and counts only.
"""

from dataclasses import dataclass
from datetime import date

from qa.application.context import AskContext, AskRequest
from qa.application.kag import KagLayer
from qa.application.retrieval import HybridLayer
from qa.application.structured import StructuredLayer
from qa.domain.answer import Answer, AnswerCitation, Layer, LayerResult, Outcome, Reason
from qa.domain.flags import KagTargeting
from qa.domain.plan import Plan
from qa.domain.ports import ProfileReader, RulebookReader, Span, Tracer


@dataclass(frozen=True, slots=True)
class LayerRecord:
    layer: Layer
    result: LayerResult
    reason: Reason | None = None


@dataclass(frozen=True, slots=True)
class AskResult:
    outcome: Outcome
    answer: str
    citations: tuple[AnswerCitation, ...]
    layer: Layer
    layers: tuple[LayerRecord, ...]
    as_of: date
    plan: Plan | None = None
    reason: Reason | None = None


class AskQuestion:
    def __init__(
        self,
        *,
        rulebook: RulebookReader,
        profiles: ProfileReader,
        structured: StructuredLayer,
        kag: KagLayer,
        hybrid: HybridLayer,
        targeting: KagTargeting,
        tracer: Tracer,
    ) -> None:
        self._rulebook = rulebook
        self._profiles = profiles
        self._structured = structured
        self._kag = kag
        self._hybrid = hybrid
        self._targeting = targeting
        self._tracer = tracer

    def run(self, request: AskRequest) -> AskResult:
        """Raises ``BusinessNotFoundError`` for a business the tenant does not have and
        ``DependencyUnavailableError`` when a service the answer needs fails."""
        ctx = AskContext(request, self._rulebook, self._profiles)
        attributes = {"qa.question_id": request.question_id, "qa.tenant_id": str(request.tenant)}
        with self._tracer.span("qa.ask", attributes) as span:
            if request.business is not None:
                ctx.profile()
            result = self._answer(ctx)
            span.set_attribute("qa.layer", result.layer.value)
            span.set_attribute("qa.outcome", result.outcome.value)
            if result.reason is not None:
                span.set_attribute("qa.reason", result.reason.value)
            return result

    def _answer(self, ctx: AskContext) -> AskResult:
        records: list[LayerRecord] = []
        with self._tracer.span("qa.layer", {"qa.layer": Layer.STRUCTURED.value}) as span:
            structured = self._structured.run(ctx)
            record = LayerRecord(
                Layer.STRUCTURED, LayerResult.PASSED if structured is None else _result(structured)
            )
            _note(span, record)
        records.append(record)
        if structured is not None:
            return _decided(ctx, Layer.STRUCTURED, structured, records, None)
        plan: Plan | None = None
        if self._targeting.is_on_for(ctx.request.tenant):
            with self._tracer.span("qa.layer", {"qa.layer": Layer.KAG.value}) as span:
                outcome = self._kag.run(ctx)
                answer = outcome.answer
                record = LayerRecord(
                    Layer.KAG,
                    LayerResult.FALLBACK if answer is None else _result(answer),
                    outcome.reason,
                )
                _note(span, record)
            records.append(record)
            plan = outcome.plan
            if answer is not None:
                return _decided(ctx, Layer.KAG, answer, records, plan)
        with self._tracer.span("qa.layer", {"qa.layer": Layer.HYBRID.value}) as span:
            hybrid = self._hybrid.run(ctx)
            record = LayerRecord(Layer.HYBRID, _result(hybrid), hybrid.reason)
            _note(span, record)
        records.append(record)
        return _decided(ctx, Layer.HYBRID, hybrid, records, plan)


def _result(answer: Answer) -> LayerResult:
    if answer.outcome is Outcome.ANSWERED:
        return LayerResult.ANSWERED
    return LayerResult.NOT_COVERED


def _note(span: Span, record: LayerRecord) -> None:
    span.set_attribute("qa.result", record.result.value)
    if record.reason is not None:
        span.set_attribute("qa.reason", record.reason.value)


def _decided(
    ctx: AskContext,
    layer: Layer,
    answer: Answer,
    records: list[LayerRecord],
    plan: Plan | None,
) -> AskResult:
    return AskResult(
        outcome=answer.outcome,
        answer=answer.text,
        citations=answer.citations,
        layer=layer,
        layers=tuple(records),
        as_of=ctx.request.as_of,
        plan=plan,
        reason=answer.reason,
    )
