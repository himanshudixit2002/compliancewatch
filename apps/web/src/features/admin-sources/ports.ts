import type {
  CrawlRun,
  CrawlStatus,
  CrawlTrigger,
  Page,
  PipelineSource,
  StoredDocument,
} from "@/entities/pipeline/types";
import type { Result } from "@/server/result";

/** The source pages' reads; the writes go through server/api/pipeline-write.ts. */
export interface SourcesPort {
  /** Every source, by key, with how each stands. */
  sources(): Promise<Result<PipelineSource[]>>;
  /** Crawl runs, the latest started first, of a source, a status or a trigger. */
  runs(query: {
    sourceKey: string | null;
    status: CrawlStatus | null;
    trigger: CrawlTrigger | null;
    limit: number;
    cursor: string | null;
  }): Promise<Result<Page<CrawlRun>>>;
  /** One source's stored documents, newest publication first, a page at a time. */
  documents(
    key: string,
    cursor: string | null,
    limit: number,
  ): Promise<Result<Page<StoredDocument>>>;
}
