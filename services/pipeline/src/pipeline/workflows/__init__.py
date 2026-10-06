"""Temporal workflows of the pipeline. Workflow code is deterministic: it only schedules the
activities in ``pipeline.application`` and combines their results."""

from pipeline.workflows.crawl_source import CRAWL_WORKFLOW, CrawlSourceWorkflow
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
    "CRAWL_WORKFLOW",
    "TASK_QUEUE",
    "CrawlSourceWorkflow",
    "ExtractKnowledgeWorkflow",
    "IngestDocumentWorkflow",
    "IngestRequest",
    "IngestResult",
    "KnowledgeRequest",
    "KnowledgeResult",
]
