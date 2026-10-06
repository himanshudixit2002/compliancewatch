import type {
  ClassificationDto,
  CrawlRunDto,
  DocumentDetailDto,
  DocumentDto,
  ExtractionDto,
  OutboxEventDto,
  PipelineDocumentDto,
  RetryDto,
  RunDto,
  SourceDto,
  TaskDto,
} from "@/entities/pipeline/types";

/**
 * The pipeline's bodies for unit tests: an example listing source and an upload-only one, crawl
 * runs, stored documents with a classification and an extraction, a retry, a task of each kind
 * and a dead outbox row. Fixed synthetic ids, "Example ..." text, dates in the year 2000. The e2e
 * suite reads the real service.
 */
export const SOURCE_KEY = "example_notices";
export const UPLOAD_SOURCE_KEY = "example_statutes";
export const RUN_ID = "00000000-0000-4000-8000-0000000000a1";
export const DOCUMENT_ID = "0a1b2c3d-4e5f-6071-8293-a4b5c6d7e8f9";
export const DOCUMENT_SHA256 = "0a1b2c3d4e5f60718293a4b5c6d7e8f900112233445566778899aabbccddeeff";
export const TASK_ID = "00000000-0000-4000-8000-0000000000b1";
export const TRIAGE_TASK_ID = "00000000-0000-4000-8000-0000000000b2";
export const EVENT_ID = "00000000-0000-4000-8000-0000000000c1";
export const CANDIDATE_ID = "00000000-0000-4000-8000-0000000000d1";
export const ACTOR_ID = "00000000-0000-4000-8000-0000000000e1";

export function crawlRunDto(overrides: Partial<CrawlRunDto> = {}): CrawlRunDto {
  return {
    run_id: RUN_ID,
    status: "completed",
    trigger: "schedule",
    workflow_id: "pipeline-crawl-example_notices-946684800",
    started_at: "2000-01-01T04:30:00Z",
    finished_at: "2000-01-01T04:31:05Z",
    listed: 12,
    stored: 3,
    duplicates: 1,
    failed: 0,
    error: "",
    ...overrides,
  };
}

export function runDto(overrides: Partial<RunDto> = {}): RunDto {
  return { ...crawlRunDto(), source_key: SOURCE_KEY, ...overrides };
}

export function sourceDto(overrides: Partial<SourceDto> = {}): SourceDto {
  return {
    key: SOURCE_KEY,
    name: "Example notices",
    adapter_type: "example",
    regulator: "EXAMPLE",
    site: "https://example.com",
    doc_type: "notification",
    parameters: { listing: "notices" },
    cadence_seconds: 7200,
    enabled: true,
    paused: false,
    listable: true,
    status: "healthy",
    document_count: 42,
    last_fetch_at: "2000-01-01T04:31:05Z",
    freshness: { state: "fresh", age_seconds: 1800, cadence_seconds: 7200, cadences: 0.25 },
    last_error: "",
    watermark: "2000-01-01",
    latest_run: crawlRunDto(),
    created_at: "2000-01-01T00:00:00Z",
    updated_at: "2000-01-01T00:00:00Z",
    ...overrides,
  };
}

export function uploadSourceDto(overrides: Partial<SourceDto> = {}): SourceDto {
  return sourceDto({
    key: UPLOAD_SOURCE_KEY,
    name: "Example statutes",
    adapter_type: "upload",
    site: null,
    doc_type: "statute",
    parameters: { document_type: "statute", regulator: "EXAMPLE" },
    cadence_seconds: 86400,
    listable: false,
    document_count: 0,
    last_fetch_at: null,
    freshness: { state: "never", age_seconds: null, cadence_seconds: 86400, cadences: null },
    watermark: null,
    latest_run: null,
    ...overrides,
  });
}

export function documentDto(overrides: Partial<DocumentDto> = {}): DocumentDto {
  return {
    document_id: DOCUMENT_ID,
    source_key: SOURCE_KEY,
    source_url: "https://example.com/notices/example-notice-1.pdf",
    title: "Example notice 1",
    external_ref: "Example 1/2000",
    published_on: "2000-01-01",
    fetched_at: "2000-01-01T04:31:00Z",
    content_type: "application/pdf",
    size: 20480,
    sha256: DOCUMENT_SHA256,
    storage_key: `0a/${DOCUMENT_SHA256}`,
    raw_path: `/v1/pipeline/documents/${DOCUMENT_ID}/raw`,
    status: "extracted",
    parser_version: "pdf@1",
    doc_type: null,
    ...overrides,
  };
}

export function classificationDto(overrides: Partial<ClassificationDto> = {}): ClassificationDto {
  return {
    doc_type: "notification",
    relevance: "relevant",
    confidence: "certain",
    route: "extract",
    classifier: "detector@1",
    decided_by: null,
    reasons: ["The opening names a notification"],
    task_id: null,
    classified_at: "2000-01-01T04:32:00Z",
    ...overrides,
  };
}

export function extractionDto(overrides: Partial<ExtractionDto> = {}): ExtractionDto {
  return {
    outcome: "extracted",
    candidate_id: CANDIDATE_ID,
    model: "example/model",
    prompt_version: "extraction.rule_candidate@1",
    issue_count: 1,
    needs_review: true,
    extracted_at: "2000-01-01T04:33:00Z",
    ...overrides,
  };
}

export function pipelineDocumentDto(
  overrides: Partial<PipelineDocumentDto> = {},
): PipelineDocumentDto {
  return {
    ...documentDto(),
    read_as: "notification",
    classification: classificationDto(),
    extraction: extractionDto(),
    ...overrides,
  };
}

export function retryDto(overrides: Partial<RetryDto> = {}): RetryDto {
  return {
    attempt: 1,
    stage: "parse",
    doc_type: null,
    reason: "Example reason for the retry",
    requested_at: "2000-01-02T05:00:00Z",
    requested_by: ACTOR_ID,
    workflow_id: `pipeline-retry-${DOCUMENT_ID}-1`,
    ...overrides,
  };
}

export function documentDetailDto(overrides: Partial<DocumentDetailDto> = {}): DocumentDetailDto {
  return { ...pipelineDocumentDto(), retries: [retryDto()], ...overrides };
}

export function taskDto(overrides: Partial<TaskDto> = {}): TaskDto {
  return {
    task_id: TASK_ID,
    kind: "manual_parse",
    status: "open",
    document_id: DOCUMENT_ID,
    document: documentDto({ status: "failed", parser_version: "" }),
    source_key: SOURCE_KEY,
    opened_at: "2000-01-01T04:34:00Z",
    reason: "pdf@1: no text layer",
    claimed_by: null,
    resolved_by: null,
    resolved_at: null,
    resolution: null,
    note: "",
    ...overrides,
  };
}

export function triageTaskDto(overrides: Partial<TaskDto> = {}): TaskDto {
  return taskDto({
    task_id: TRIAGE_TASK_ID,
    kind: "triage",
    document: documentDto({ status: "triage" }),
    reason: "The opening names a circular; the source publishes notifications",
    ...overrides,
  });
}

export function outboxEventDto(overrides: Partial<OutboxEventDto> = {}): OutboxEventDto {
  return {
    event_id: EVENT_ID,
    topic: "document.parsed",
    key: "00000000-0000-4000-8000-0000000000f1",
    status: "dead",
    attempts: 8,
    last_error: "Example broker error",
    created_at: "2000-01-01T04:35:00Z",
    occurred_at: "2000-01-01T04:35:00Z",
    dead_at: "2000-01-01T05:00:00Z",
    published_at: null,
    payload_bytes: 512,
    schema_version: "1.1.0",
    summary: { document_id: DOCUMENT_ID, source_key: SOURCE_KEY },
    ...overrides,
  };
}
