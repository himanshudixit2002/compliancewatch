"""Temporal workflows of the pipeline. Workflow code is deterministic: it only schedules the
activities in ``pipeline.application`` and combines their results."""

from pipeline.workflows.extract_knowledge import (
    ExtractKnowledgeWorkflow,
    KnowledgeRequest,
    KnowledgeResult,
)
from pipeline.workflows.ingest_document import (
    TASK_QUEUE,
    IngestDocumentWorkflow,
    IngestRequest,
    IngestResult,
)

__all__ = [
    "TASK_QUEUE",
    "ExtractKnowledgeWorkflow",
    "IngestDocumentWorkflow",
    "IngestRequest",
    "IngestResult",
    "KnowledgeRequest",
    "KnowledgeResult",
]
