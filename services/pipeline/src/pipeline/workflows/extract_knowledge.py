"""Extract the knowledge in one stored document: its mentions, then the relations it states.

A child of the ingest workflow, run once the document is registered in the rulebook. Three
activities: the mention grammar with alignment, the model's relation proposals (validated, no
write), and staging them for review. The proposals cross the workflow as data, so a failed
write is retried without asking the model again.
"""

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from uuid import UUID

    from pipeline.application.activities import Frozen
    from pipeline.application.knowledge_activities import (
        ExtractMentions,
        MentionsRequest,
        ProposeRelations,
        RelationsRequest,
        SubmitRelations,
    )


class KnowledgeRequest(Frozen):
    document_id: UUID
    own_ref: str = ""
    regulator: str = ""


class KnowledgeResult(Frozen):
    mentions_found: int = 0
    mentions_aligned: int = 0
    mentions_queued: int = 0
    relations_outcome: str = "skipped"
    relations_staged: int = 0


@workflow.defn(name="pipeline.extract_knowledge")
class ExtractKnowledgeWorkflow:
    @workflow.run
    async def run(self, request: KnowledgeRequest) -> KnowledgeResult:
        mentions = await ExtractMentions.schedule(
            MentionsRequest(document_id=request.document_id, own_ref=request.own_ref)
        )
        batch = await ProposeRelations.schedule(
            RelationsRequest(
                document_id=request.document_id,
                own_ref=request.own_ref,
                regulator=request.regulator,
            )
        )
        staged = await SubmitRelations.schedule(batch)
        return KnowledgeResult(
            mentions_found=mentions.found,
            mentions_aligned=mentions.aligned,
            mentions_queued=mentions.queued,
            relations_outcome="skipped" if staged.skipped else staged.outcome,
            relations_staged=staged.created + staged.unchanged,
        )
