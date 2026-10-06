import type {
  CrawlRun,
  CrawlStatus,
  CrawlTrigger,
  DocumentDetail,
  DocumentStatus,
  DocumentType,
  OutboxEvent,
  Page,
  PipelineDocument,
  PipelineTask,
  TaskKind,
  TaskStatus,
} from "@/entities/pipeline/types";
import type { Result } from "@/server/result";

export interface RunQuery {
  sourceKey: string | null;
  status: CrawlStatus | null;
  trigger: CrawlTrigger | null;
  limit: number;
  cursor: string | null;
}

export interface DocumentQuery {
  status: DocumentStatus | null;
  sourceKey: string | null;
  docType: DocumentType | null;
  publishedFrom: string | null;
  publishedTo: string | null;
  limit: number;
  cursor: string | null;
}

export interface DeadEventQuery {
  topic: string | null;
  limit: number;
  cursor: string | null;
}

export interface TaskQuery {
  status: TaskStatus | null;
  kind: TaskKind | null;
  limit: number;
  cursor: string | null;
}

/** The pipeline pages' reads; the writes go through server/api/pipeline-write.ts. */
export interface PipelinePort {
  runs(query: RunQuery): Promise<Result<Page<CrawlRun>>>;
  documents(query: DocumentQuery): Promise<Result<Page<PipelineDocument>>>;
  document(documentId: string): Promise<Result<DocumentDetail>>;
  deadEvents(query: DeadEventQuery): Promise<Result<Page<OutboxEvent>>>;
  tasks(query: TaskQuery): Promise<Result<Page<PipelineTask>>>;
  /** The sources' keys, for the filters. */
  sourceKeys(): Promise<Result<string[]>>;
}
