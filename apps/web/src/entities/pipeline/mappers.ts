import type {
  Classification,
  ClassificationDto,
  CrawlRun,
  CrawlRunDto,
  DocumentDetail,
  DocumentDetailDto,
  DocumentDto,
  DocumentRetry,
  Extraction,
  ExtractionDto,
  FetchOutDto,
  FetchStarted,
  Freshness,
  FreshnessDto,
  OutboxEvent,
  OutboxEventDto,
  Page,
  PipelineDocument,
  PipelineDocumentDto,
  PipelineSource,
  PipelineTask,
  Requeued,
  RequeueOutDto,
  ResolutionDto,
  RetryAccepted,
  RetryAcceptedDto,
  RetryDto,
  RunDto,
  SourceDto,
  SourceEdit,
  SourceEditDto,
  StoredDocument,
  TaskDto,
  TaskResolved,
  Transcript,
  TranscriptDto,
  TriageDecision,
  TriageDto,
  UploadOutDto,
  UploadStored,
} from "./types";

/**
 * The pipeline's bodies to the web app's records and back. Every field is copied by name, an
 * absent optional is null, and a record from the wire (parameters, a resolution, an outbox
 * summary) is copied rather than shared. The bodies a write sends name the acting admin as
 * `actor_id`, which the caller passes from the session.
 */
export function freshnessFromDto(dto: FreshnessDto): Freshness {
  return {
    state: dto.state,
    ageSeconds: dto.age_seconds ?? null,
    cadenceSeconds: dto.cadence_seconds,
    cadences: dto.cadences ?? null,
  };
}

export function crawlRunFromDto(dto: CrawlRunDto | RunDto): CrawlRun {
  return {
    runId: dto.run_id,
    sourceKey: "source_key" in dto ? dto.source_key : null,
    status: dto.status,
    trigger: dto.trigger ?? null,
    workflowId: dto.workflow_id ?? null,
    startedAt: dto.started_at,
    finishedAt: dto.finished_at ?? null,
    listed: dto.listed,
    stored: dto.stored,
    duplicates: dto.duplicates,
    failed: dto.failed,
    error: dto.error,
  };
}

export function sourceFromDto(dto: SourceDto): PipelineSource {
  return {
    key: dto.key,
    name: dto.name,
    adapterType: dto.adapter_type,
    regulator: dto.regulator ?? null,
    site: dto.site ?? null,
    docType: dto.doc_type ?? null,
    parameters: { ...dto.parameters },
    cadenceSeconds: dto.cadence_seconds,
    enabled: dto.enabled,
    paused: dto.paused,
    listable: dto.listable,
    status: dto.status,
    documentCount: dto.document_count,
    lastFetchAt: dto.last_fetch_at ?? null,
    freshness: freshnessFromDto(dto.freshness),
    lastError: dto.last_error,
    watermark: dto.watermark ?? null,
    latestRun:
      dto.latest_run === null || dto.latest_run === undefined
        ? null
        : crawlRunFromDto(dto.latest_run),
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
  };
}

export function storedDocumentFromDto(dto: DocumentDto): StoredDocument {
  return {
    documentId: dto.document_id,
    sourceKey: dto.source_key,
    sourceUrl: dto.source_url,
    title: dto.title,
    externalRef: dto.external_ref,
    publishedOn: dto.published_on ?? null,
    fetchedAt: dto.fetched_at,
    contentType: dto.content_type,
    size: dto.size,
    sha256: dto.sha256,
    storageKey: dto.storage_key,
    status: dto.status,
    parserVersion: dto.parser_version,
    uploaderType: dto.doc_type ?? null,
  };
}

export function classificationFromDto(dto: ClassificationDto): Classification {
  return {
    docType: dto.doc_type,
    relevance: dto.relevance,
    confidence: dto.confidence,
    route: dto.route,
    classifier: dto.classifier,
    decidedBy: dto.decided_by ?? null,
    reasons: [...dto.reasons],
    taskId: dto.task_id ?? null,
    classifiedAt: dto.classified_at,
  };
}

export function extractionFromDto(dto: ExtractionDto): Extraction {
  return {
    outcome: dto.outcome,
    candidateId: dto.candidate_id,
    model: dto.model,
    promptVersion: dto.prompt_version,
    issueCount: dto.issue_count,
    needsReview: dto.needs_review,
    extractedAt: dto.extracted_at,
  };
}

export function retryFromDto(dto: RetryDto): DocumentRetry {
  return {
    attempt: dto.attempt,
    stage: dto.stage,
    docType: dto.doc_type ?? null,
    reason: dto.reason,
    requestedAt: dto.requested_at,
    requestedBy: dto.requested_by ?? null,
    workflowId: dto.workflow_id,
  };
}

export function pipelineDocumentFromDto(dto: PipelineDocumentDto): PipelineDocument {
  return {
    ...storedDocumentFromDto(dto),
    readAs: dto.read_as ?? null,
    classification:
      dto.classification === null || dto.classification === undefined
        ? null
        : classificationFromDto(dto.classification),
    extraction:
      dto.extraction === null || dto.extraction === undefined
        ? null
        : extractionFromDto(dto.extraction),
  };
}

export function documentDetailFromDto(dto: DocumentDetailDto): DocumentDetail {
  return { ...pipelineDocumentFromDto(dto), retries: dto.retries.map(retryFromDto) };
}

export function taskFromDto(dto: TaskDto): PipelineTask {
  return {
    taskId: dto.task_id,
    kind: dto.kind,
    status: dto.status,
    sourceKey: dto.source_key,
    document: storedDocumentFromDto(dto.document),
    openedAt: dto.opened_at,
    reason: dto.reason,
    claimedBy: dto.claimed_by ?? null,
    resolvedBy: dto.resolved_by ?? null,
    resolvedAt: dto.resolved_at ?? null,
    resolution:
      dto.resolution === null || dto.resolution === undefined ? null : { ...dto.resolution },
    note: dto.note,
  };
}

export function outboxEventFromDto(dto: OutboxEventDto): OutboxEvent {
  return {
    eventId: dto.event_id,
    topic: dto.topic,
    key: dto.key,
    status: dto.status,
    attempts: dto.attempts,
    lastError: dto.last_error,
    createdAt: dto.created_at,
    occurredAt: dto.occurred_at,
    deadAt: dto.dead_at ?? null,
    publishedAt: dto.published_at ?? null,
    payloadBytes: dto.payload_bytes,
    schemaVersion: dto.schema_version,
    summary: { ...dto.summary },
  };
}

/** A page body (`items`, `next_cursor`) mapped item by item. */
export function pageFromDto<D, T>(
  dto: { items: readonly D[]; next_cursor?: string | null },
  item: (value: D) => T,
): Page<T> {
  return { items: dto.items.map(item), nextCursor: dto.next_cursor ?? null };
}

export function fetchStartedFromDto(dto: FetchOutDto): FetchStarted {
  return {
    runId: dto.run_id,
    sourceKey: dto.source_key,
    trigger: dto.trigger,
    workflowId: dto.workflow_id,
  };
}

export function retryAcceptedFromDto(dto: RetryAcceptedDto): RetryAccepted {
  return {
    retry: retryFromDto(dto.retry),
    document: documentDetailFromDto(dto.document),
    started: dto.started,
    reclassified: dto.reclassified,
    workflowId: dto.workflow_id,
  };
}

export function requeuedFromDto(dto: RequeueOutDto): Requeued {
  return { event: outboxEventFromDto(dto.event), requeued: dto.requeued };
}

export function taskResolvedFromDto(dto: ResolutionDto): TaskResolved {
  return { task: taskFromDto(dto.task), started: dto.started, workflowId: dto.workflow_id };
}

export function uploadStoredFromDto(dto: UploadOutDto): UploadStored {
  return {
    document: storedDocumentFromDto(dto.document),
    duplicate: dto.duplicate,
    workflowId: dto.workflow_id,
  };
}

/** The PATCH body: the changed fields only, the reason and the acting admin. */
export function sourceEditToDto(edit: SourceEdit, actorId: string, reason: string): SourceEditDto {
  return {
    actor_id: actorId,
    reason,
    ...(edit.name === undefined ? {} : { name: edit.name }),
    ...(edit.cadenceSeconds === undefined ? {} : { cadence_seconds: edit.cadenceSeconds }),
    ...(edit.enabled === undefined ? {} : { enabled: edit.enabled }),
    ...(edit.paused === undefined ? {} : { paused: edit.paused }),
    ...(edit.parameters === undefined ? {} : { parameters: { ...edit.parameters } }),
  };
}

/** A transcript in the resolve body's shape: optional pages and numbers only when there are. */
export function transcriptToDto(transcript: Transcript): TranscriptDto {
  return {
    title: transcript.title,
    blocks: transcript.blocks.map((block) => {
      const page = block.page === null ? {} : { page: block.page };
      if (block.type === "heading") return { type: "heading", text: block.text, ...page };
      if (block.type === "paragraph") {
        return {
          type: "paragraph",
          text: block.text,
          ...(block.number === "" ? {} : { number: block.number }),
          ...page,
        };
      }
      return {
        type: "table",
        rows: block.rows.map((row) => [...row]),
        ...(block.header === null ? {} : { header: [...block.header] }),
        ...page,
      };
    }),
  };
}

/** A triage decision in the resolve body's shape. */
export function triageToDto(decision: TriageDecision): TriageDto {
  return decision.relevance === "relevant"
    ? { relevance: "relevant", doc_type: decision.docType }
    : { relevance: "irrelevant" };
}
