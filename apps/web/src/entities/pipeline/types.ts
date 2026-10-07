import type { pipeline } from "@compliancewatch/contracts/openapi";
import { membersOf } from "@/shared/lib/union";

/**
 * The pipeline's records as its source manager and its operations routes report them: the
 * sources it reads, their crawl runs, the documents it stored with how it reads each one (its
 * classification and its rule extraction by the current prompt), the retries people asked for,
 * the tasks people work on, and the outbox rows the relay gave up on. None belongs to a tenant.
 * Instants are ISO strings with an offset and dates are YYYY-MM-DD, as the service sends them;
 * the views format both in IST.
 */
type Schemas = pipeline.components["schemas"];

export type SourceDto = Schemas["SourceOut"];
export type SourcesDto = Schemas["SourcesOut"];
export type SourceEditDto = Schemas["SourceEditIn"];
export type CrawlRunDto = Schemas["CrawlRunOut"];
export type RunDto = Schemas["RunOut"];
export type FreshnessDto = Schemas["FreshnessOut"];
export type DocumentDto = Schemas["DocumentOut"];
export type PipelineDocumentDto = Schemas["PipelineDocumentOut"];
export type DocumentDetailDto = Schemas["DocumentDetailOut"];
export type ClassificationDto = Schemas["ClassificationOut"];
export type ExtractionDto = Schemas["ExtractionOut"];
export type RetryDto = Schemas["RetryOut"];
export type RetryInDto = Schemas["RetryIn"];
export type RetryAcceptedDto = Schemas["RetryAcceptedOut"];
export type FetchOutDto = Schemas["FetchOut"];
export type TaskDto = Schemas["TaskOut"];
export type ResolutionDto = Schemas["ResolutionOut"];
export type ResolveInDto = Schemas["ResolveIn"];
export type TranscriptDto = Schemas["TranscriptIn"];
export type TranscriptBlockDto = TranscriptDto["blocks"][number];
export type TriageDto = Schemas["TriageIn"];
export type DismissInDto = Schemas["DismissIn"];
export type RequeueInDto = Schemas["RequeueIn"];
export type FetchInDto = Schemas["FetchIn"];
export type OutboxEventDto = Schemas["OutboxEventOut"];
export type RequeueOutDto = Schemas["RequeueOut"];
export type UploadOutDto = Schemas["UploadOut"];
export type UploadFormDto = Schemas["Body_upload_document_v1_pipeline_sources__key__uploads_post"];

export type DocumentStatus = Schemas["DocumentStatus"];
export type DocumentType = Schemas["DocumentType"];
export type CrawlStatus = Schemas["CrawlStatus"];
export type CrawlTrigger = Schemas["CrawlTrigger"];
export type SourceStatus = Schemas["SourceStatus"];
export type FreshnessState = Schemas["FreshnessState"];
export type TaskKind = Schemas["TaskKind"];
export type TaskStatus = Schemas["TaskStatus"];
export type RetryStage = Schemas["RetryStage"];
export type Relevance = Schemas["Relevance"];
export type ClassificationRoute = Schemas["Route"];
export type TypeConfidence = Schemas["TypeConfidence"];
export type ExtractionOutcome = Schemas["ExtractionOutcome"];
export type OutboxStatus = Schemas["OutboxStatus"];

/** Where a stored document stands, in the order the pipeline moves a document along. */
export const DOCUMENT_STATUSES = membersOf<DocumentStatus>({
  discovered: true,
  parsed: true,
  failed: true,
  irrelevant: true,
  classified: true,
  triage: true,
  reference: true,
  extracted: true,
});

/** What a regulator document is. */
export const DOCUMENT_TYPES = membersOf<DocumentType>({
  notification: true,
  circular: true,
  press_release: true,
  act_amendment: true,
  statute: true,
});

/** The types a rule is extracted from; the others are kept for reference. */
export const EXTRACTED_TYPES = [
  "notification",
  "circular",
  "act_amendment",
] as const satisfies readonly DocumentType[];

export const CRAWL_STATUSES = membersOf<CrawlStatus>({
  running: true,
  completed: true,
  failed: true,
});

export const CRAWL_TRIGGERS = membersOf<CrawlTrigger>({
  schedule: true,
  manual: true,
  backfill: true,
});

export const SOURCE_STATUSES = membersOf<SourceStatus>({
  healthy: true,
  fetching: true,
  failing: true,
  paused: true,
});

export const FRESHNESS_STATES = membersOf<FreshnessState>({
  fresh: true,
  late: true,
  stale: true,
  never: true,
});

export const TASK_KINDS = membersOf<TaskKind>({ manual_parse: true, triage: true });

export const TASK_STATUSES = membersOf<TaskStatus>({ open: true, resolved: true, dismissed: true });

export const RETRY_STAGES = membersOf<RetryStage>({ parse: true, classify: true, extract: true });

export const RELEVANCES = membersOf<Relevance>({ relevant: true, irrelevant: true });

export const CLASSIFICATION_ROUTES = membersOf<ClassificationRoute>({
  extract: true,
  reference: true,
  irrelevant: true,
  triage: true,
});

export const TYPE_CONFIDENCES = membersOf<TypeConfidence>({
  certain: true,
  default: true,
  conflict: true,
});

export const EXTRACTION_OUTCOMES = membersOf<ExtractionOutcome>({
  extracted: true,
  unparseable: true,
});

export const OUTBOX_STATUSES = membersOf<OutboxStatus>({
  pending: true,
  published: true,
  dead: true,
});

/** How long since a crawl last listed a source, against its cadence. */
export interface Freshness {
  state: FreshnessState;
  /** Seconds since a crawl last listed the source; null before the first one. */
  ageSeconds: number | null;
  cadenceSeconds: number;
  /** The age in cadences, two decimals; null before the first listing. */
  cadences: number | null;
}

/** One crawl run; `sourceKey` is null on the run a source carries as its latest. */
export interface CrawlRun {
  runId: string;
  sourceKey: string | null;
  status: CrawlStatus;
  /** Why it ran; null on a run recorded before the pipeline kept it. */
  trigger: CrawlTrigger | null;
  /** The crawl's workflow on Temporal; null on a run recorded before it was kept. */
  workflowId: string | null;
  startedAt: string;
  finishedAt: string | null;
  listed: number;
  stored: number;
  duplicates: number;
  failed: number;
  error: string;
}

/** A source the pipeline reads. */
export interface PipelineSource {
  key: string;
  /** Its name, or its key when it has none. */
  name: string;
  adapterType: string;
  /** From the adapter type; null when the code cannot read the source's type. */
  regulator: string | null;
  site: string | null;
  docType: DocumentType | null;
  parameters: Readonly<Record<string, unknown>>;
  cadenceSeconds: number;
  enabled: boolean;
  paused: boolean;
  /** Whether it lists documents, so the schedule crawls it; false for an upload-only source. */
  listable: boolean;
  status: SourceStatus;
  documentCount: number;
  /** When a crawl last listed it. */
  lastFetchAt: string | null;
  freshness: Freshness;
  lastError: string;
  /** The newest publication date up to which every listed document is stored. */
  watermark: string | null;
  latestRun: CrawlRun | null;
  createdAt: string;
  updatedAt: string;
}

/** A stored document as its record holds it. */
export interface StoredDocument {
  documentId: string;
  sourceKey: string;
  sourceUrl: string;
  title: string;
  externalRef: string;
  publishedOn: string | null;
  fetchedAt: string;
  contentType: string;
  size: number;
  sha256: string;
  storageKey: string;
  status: DocumentStatus;
  /** The parser of its last parse; empty before one. */
  parserVersion: string;
  /** The type its uploader gave; null when it is its source's. */
  uploaderType: DocumentType | null;
}

/** How the pipeline classified a document. */
export interface Classification {
  docType: DocumentType;
  relevance: Relevance;
  confidence: TypeConfidence;
  route: ClassificationRoute;
  /** detector@1, triage or retry. */
  classifier: string;
  /** The person whose decision it is, if one's. */
  decidedBy: string | null;
  reasons: readonly string[];
  taskId: string | null;
  classifiedAt: string;
}

/** The document's rule extraction by the current prompt. */
export interface Extraction {
  outcome: ExtractionOutcome;
  candidateId: string;
  model: string;
  promptVersion: string;
  issueCount: number;
  needsReview: boolean;
  extractedAt: string;
}

/** One retry a person asked for. */
export interface DocumentRetry {
  attempt: number;
  stage: RetryStage;
  /** The type the person gave; null when its classification stood. */
  docType: DocumentType | null;
  reason: string;
  requestedAt: string;
  requestedBy: string | null;
  workflowId: string;
}

/** A stored document with how the pipeline reads it. */
export interface PipelineDocument extends StoredDocument {
  /** Its classification's type, else its uploader's, else its source's. */
  readAs: DocumentType | null;
  classification: Classification | null;
  extraction: Extraction | null;
}

/** One document with the retries people asked for. */
export interface DocumentDetail extends PipelineDocument {
  retries: readonly DocumentRetry[];
}

/** A task people work on a stored document. */
export interface PipelineTask {
  taskId: string;
  kind: TaskKind;
  status: TaskStatus;
  sourceKey: string;
  document: StoredDocument;
  openedAt: string;
  /** Why it opened: each parser's reason, or the classifier's. */
  reason: string;
  claimedBy: string | null;
  resolvedBy: string | null;
  resolvedAt: string | null;
  /** What the resolution did, as the pipeline recorded it. */
  resolution: Readonly<Record<string, unknown>> | null;
  /** The resolver's or dismisser's reason. */
  note: string;
}

/** An outbox row without its body. */
export interface OutboxEvent {
  eventId: string;
  topic: string;
  /** The Kafka message key (the event's source). */
  key: string;
  status: OutboxStatus;
  /** Failed sends since it was written or last requeued. */
  attempts: number;
  lastError: string;
  createdAt: string;
  occurredAt: string;
  deadAt: string | null;
  publishedAt: string | null;
  payloadBytes: number;
  schemaVersion: string;
  /** What the event is about, from its payload; never the body. */
  summary: Readonly<Record<string, unknown>>;
}

/** A page of a keyset-paged list and the cursor of the next one (null on the last). */
export interface Page<T> {
  items: readonly T[];
  nextCursor: string | null;
}

/** What an admin changes on a source; a field left out stays. */
export interface SourceEdit {
  name?: string;
  cadenceSeconds?: number;
  enabled?: boolean;
  paused?: boolean;
  parameters?: Readonly<Record<string, unknown>>;
}

/** The crawl a fetch started. */
export interface FetchStarted {
  runId: string;
  sourceKey: string;
  trigger: CrawlTrigger;
  workflowId: string;
}

/** A retry's answer: the attempt and whether its ingest started now. */
export interface RetryAccepted {
  retry: DocumentRetry;
  document: DocumentDetail;
  /** False when the ingest was started before (a request sent again under its key). */
  started: boolean;
  /** Whether the person's type reclassified the document. */
  reclassified: boolean;
  workflowId: string;
}

/** A requeue's answer: the row as it stands, and whether it was put back to pending. */
export interface Requeued {
  event: OutboxEvent;
  /** False for a row that was not dead, which nothing changed. */
  requeued: boolean;
}

/** A task's resolution and the ingest it starts. */
export interface TaskResolved {
  task: PipelineTask;
  /** False when the ingest was started before (it runs, or it is done). */
  started: boolean;
  /** Empty for an irrelevant triage, which starts none. */
  workflowId: string;
}

/** A triage decision: relevant with a type, or irrelevant. */
export type TriageDecision =
  { relevance: "relevant"; docType: DocumentType } | { relevance: "irrelevant" };

/** A transcript block, in the shape of the parsers' blocks. */
export type TranscriptBlock =
  | { type: "heading"; text: string; page: number | null }
  | { type: "paragraph"; number: string; text: string; page: number | null }
  | {
      type: "table";
      header: readonly string[] | null;
      rows: readonly (readonly string[])[];
      page: number | null;
    };

/** A document typed by hand. */
export interface Transcript {
  title: string;
  blocks: readonly TranscriptBlock[];
}

/** An upload's answer, as the upload handler gives it to the page. */
export interface UploadStored {
  document: StoredDocument;
  /** The bytes were stored before: nothing was recorded again, and the ingest ran again. */
  duplicate: boolean;
  workflowId: string;
}
