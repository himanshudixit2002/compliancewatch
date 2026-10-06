"""Extract the documents that wait as ``classified``: the backlog left while the extraction was off.

``pipeline.extract_backlog`` (``ExtractBacklogWorkflow``) first asks the worker whether it
extracts (``pipeline.extraction_enabled``, ``CheckExtraction``). While it does not, the sweep starts
nothing and counts every document ``skipped``: a child started then would end ``disabled`` with
its id used, and that id may be reused only after a failure, so the document's extraction would
never run again (until Temporal's retention drops the closed run). Otherwise it runs the rule
extraction of each document it is given as a child ``pipeline.extract_rules``
(``workflows.extract_rules``), at most ``concurrency`` at a time, under the id the ingest's own
child would have (``extraction_workflow_id``): a document whose extraction runs or ran is counted
``running`` and asked about no more. A child a worker with the extraction off ran all the same
(the flag turned off meanwhile, or workers that differ) is counted ``disabled``, apart from the
running ones: its id is used now. A child waits out a used-up budget as it does under an ingest,
so the sweep may run as long. Children are abandoned, not cancelled, if the sweep ends early: what
they store stays stored. A child that fails counts as failed with why (a document the rulebook
does not hold fails at once: retry it from parse while knowledge is on).
``pipeline-extract-backlog`` (``pipeline.backlog``) lists the backlog and starts the sweep; the
workflow itself does no I/O.
"""

import asyncio
from typing import Final

from temporalio import workflow
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ChildWorkflowError, WorkflowAlreadyStartedError

with workflow.unsafe.imports_passed_through():
    from pydantic import Field

    from pipeline.application.activities import Frozen
    from pipeline.application.extraction import (
        RULE_PROMPT_REF,
        CheckExtraction,
        ExtractionCheck,
        ExtractionRequest,
    )
    from pipeline.domain.extraction import extraction_workflow_id
    from pipeline.workflows.extract_rules import (
        EXTRACTION_TIMEOUT,
        ExtractionResult,
        ExtractRulesWorkflow,
    )
    from pipeline.workflows.ingest_document import failure_text

EXTRACT_BACKLOG_WORKFLOW: Final = "pipeline.extract_backlog"
DEFAULT_CONCURRENCY: Final = 3
MAX_CONCURRENCY: Final = 10
MAX_DOCUMENTS: Final = 1_000
MAX_FAILURES_KEPT: Final = 20


class BacklogRequest(Frozen):
    """The documents to extract, as the ingest would hand each to its extraction, and how many
    extractions run at once."""

    documents: list[ExtractionRequest] = Field(min_length=1, max_length=MAX_DOCUMENTS)
    concurrency: int = Field(default=DEFAULT_CONCURRENCY, ge=1, le=MAX_CONCURRENCY)


class BacklogResult(Frozen):
    """What became of the documents: extracted (a candidate stored now or before), unparseable
    (stored with no candidate), running (an extraction of the id runs or ran), disabled (a worker
    with the extraction off ran it: its id is used), skipped (none started: the worker's
    extraction is off, ``extraction_enabled``), failed (with the first few failures,
    ``<document>: <why>``)."""

    documents: int
    extracted: int = 0
    unparseable: int = 0
    running: int = 0
    disabled: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[str] = Field(default_factory=list)
    extraction_enabled: bool = True


@workflow.defn(name=EXTRACT_BACKLOG_WORKFLOW)
class ExtractBacklogWorkflow:
    @workflow.run
    async def run(self, request: BacklogRequest) -> BacklogResult:
        switch = await CheckExtraction.schedule(ExtractionCheck())
        if not switch.enabled:
            workflow.logger.warning(
                "the worker's extraction is off: the sweep starts none of %s extractions",
                len(request.documents),
            )
            return BacklogResult(
                documents=len(request.documents),
                skipped=len(request.documents),
                extraction_enabled=False,
            )
        gate = asyncio.Semaphore(request.concurrency)
        outcomes = await asyncio.gather(
            *(self._extract(document, gate) for document in request.documents)
        )
        failures = [outcome for outcome in outcomes if outcome.startswith("failed:")]
        return BacklogResult(
            documents=len(request.documents),
            extracted=outcomes.count("extracted"),
            unparseable=outcomes.count("unparseable"),
            running=outcomes.count("running"),
            disabled=outcomes.count("disabled"),
            failed=len(failures),
            failures=[failure.removeprefix("failed:") for failure in failures][:MAX_FAILURES_KEPT],
        )

    async def _extract(self, document: ExtractionRequest, gate: asyncio.Semaphore) -> str:
        async with gate:
            try:
                result: ExtractionResult = await workflow.execute_child_workflow(
                    ExtractRulesWorkflow.run,
                    document,
                    id=extraction_workflow_id(document.document_id, RULE_PROMPT_REF),
                    task_queue=workflow.info().task_queue,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                    parent_close_policy=workflow.ParentClosePolicy.ABANDON,
                    execution_timeout=EXTRACTION_TIMEOUT,
                )
            except WorkflowAlreadyStartedError:
                return "running"
            except ChildWorkflowError as error:
                return f"failed:{document.document_id}: {failure_text(error)[:300]}"
        if result.outcome in ("unparseable", "disabled"):
            return result.outcome
        return "extracted" if result.outcome == "extracted" else "running"
