"""Temporal workflows of the pipeline. Workflow code is deterministic: it only schedules the
activities in ``pipeline.application`` and combines their results."""

from pipeline.workflows.crawl_source import CRAWL_WORKFLOW, CrawlSourceWorkflow
from pipeline.workflows.extract_backlog import (
    EXTRACT_BACKLOG_WORKFLOW,
    BacklogRequest,
    BacklogResult,
    ExtractBacklogWorkflow,
)
from pipeline.workflows.extract_knowledge import (
    ExtractKnowledgeWorkflow,
    KnowledgeRequest,
    KnowledgeResult,
)
from pipeline.workflows.extract_rules import (
    EXTRACT_RULES_WORKFLOW,
    ExtractionResult,
    ExtractRulesWorkflow,
)
from pipeline.workflows.ingest_document import (
    TASK_QUEUE,
    IngestDocumentWorkflow,
    IngestRequest,
    IngestResult,
)

__all__ = [
    "CRAWL_WORKFLOW",
    "EXTRACT_BACKLOG_WORKFLOW",
    "EXTRACT_RULES_WORKFLOW",
    "TASK_QUEUE",
    "BacklogRequest",
    "BacklogResult",
    "CrawlSourceWorkflow",
    "ExtractBacklogWorkflow",
    "ExtractKnowledgeWorkflow",
    "ExtractRulesWorkflow",
    "ExtractionResult",
    "IngestDocumentWorkflow",
    "IngestRequest",
    "IngestResult",
    "KnowledgeRequest",
    "KnowledgeResult",
]
