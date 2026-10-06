"""Extract one classified document's rule candidate: ask the model, then store the answer.

``pipeline.extract_rules`` (``ExtractRulesWorkflow``) is a child the ingest starts and leaves
running (``ParentClosePolicy.ABANDON``): the ingest, and the crawl above it, never wait for a
model. Two activities (``application.extraction``): ``pipeline.extract_rules`` asks the model
(once more when its answer is not a candidate) and writes nothing; ``pipeline.store_extraction``
stores the answer with its ``rule.candidate.created`` in one transaction. The answer crosses the
workflow as data, so a failed write is retried without asking the model again.

A budget the gateway says is used up does not fail the extraction: the workflow sleeps (a
durable timer) for the gateway's ``Retry-After``, kept between the request's
``min_wait_seconds`` and ``max_wait_seconds`` (15 minutes and 6 hours), and asks again, at most
``max_waits`` times. This replaces a deferral queue in the gateway. Any other failure fails the
workflow, and the document stays ``classified``.
"""

from datetime import timedelta
from typing import Final

from temporalio import workflow
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from pipeline.application.activities import Frozen
    from pipeline.application.extraction import (
        BUDGET_ERROR,
        ExtractionRequest,
        ExtractRules,
        StoreExtraction,
    )
    from pipeline.application.extractor import FEATURE
    from pipeline.domain.extraction import extraction_workflow_id as extraction_workflow_id

EXTRACT_RULES_WORKFLOW: Final = "pipeline.extract_rules"
EXTRACTION_TIMEOUT: Final = timedelta(days=45)
"""Long enough for the budget waits (some 40 days at most) and the asks between them."""


def budget_wait(error: ActivityError) -> float | None:
    """The gateway's ``Retry-After`` (0 when it sent none) when the attempt failed for a used-up
    budget; None for any other failure."""
    cause = error.cause
    if not isinstance(cause, ApplicationError) or cause.type != BUDGET_ERROR:
        return None
    details = cause.details
    first = details[0] if details else None
    return float(first) if isinstance(first, int | float) else 0.0


class ExtractionResult(Frozen):
    """``outcome`` is ``extracted``, ``unparseable`` or ``disabled``; ``created`` says the
    candidate was stored now (False for one stored before); ``budget_waits`` counts the waits
    for a used-up budget."""

    document_id: UUID
    outcome: str
    candidate_id: UUID | None = None
    needs_review: bool = True
    created: bool = False
    attempts: int = 0
    budget_waits: int = 0


@workflow.defn(name=EXTRACT_RULES_WORKFLOW)
class ExtractRulesWorkflow:
    @workflow.run
    async def run(self, request: ExtractionRequest) -> ExtractionResult:
        waits = 0
        while True:
            try:
                answer = await ExtractRules.schedule(request)
                break
            except ActivityError as error:
                retry_after = budget_wait(error)
                if retry_after is None or waits >= request.max_waits:
                    raise
                seconds = min(
                    max(retry_after or request.max_wait_seconds, request.min_wait_seconds),
                    request.max_wait_seconds,
                )
                waits += 1
                workflow.logger.warning(
                    "the %s budget is used up; asking again in %s s (wait %s of %s)",
                    FEATURE,
                    seconds,
                    waits,
                    request.max_waits,
                )
                await workflow.sleep(timedelta(seconds=seconds))
        if answer.skipped:
            return ExtractionResult(
                document_id=request.document_id, outcome="disabled", budget_waits=waits
            )
        stored = await StoreExtraction.schedule(answer)
        return ExtractionResult(
            document_id=request.document_id,
            outcome=stored.outcome,
            candidate_id=stored.candidate_id,
            needs_review=stored.needs_review,
            created=stored.created,
            attempts=answer.attempts,
            budget_waits=waits,
        )
