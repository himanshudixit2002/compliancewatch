import "server-only";

import {
  crawlRunFromDto,
  pageFromDto,
  sourceFromDto,
  storedDocumentFromDto,
} from "@/entities/pipeline/mappers";
import type {
  CrawlRun,
  CrawlStatus,
  CrawlTrigger,
  Page,
  PipelineSource,
  StoredDocument,
} from "@/entities/pipeline/types";
import { call } from "@/server/api/client";
import { pipelineClient, type ClientContext, type PipelineClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { SourcesPort } from "./ports";

/**
 * The source pages over the typed pipeline client, with no tenant header and no token. Nothing is
 * cached: the crawl moves a source's status, freshness and runs, and an admin's edit, fetch or
 * upload changes them, outside this server.
 */
export class SourcesGateway implements SourcesPort {
  private readonly pipeline: PipelineClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.pipeline = pipelineClient(ctx);
  }

  async sources(): Promise<Result<PipelineSource[]>> {
    const result = await call(this.pipeline.GET("/v1/pipeline/sources", { ...uncachedRead() }));
    return mapBody(result, (body) => body.items.map(sourceFromDto));
  }

  async runs(query: {
    sourceKey: string | null;
    status: CrawlStatus | null;
    trigger: CrawlTrigger | null;
    limit: number;
    cursor: string | null;
  }): Promise<Result<Page<CrawlRun>>> {
    const result = await call(
      this.pipeline.GET("/v1/pipeline/runs", {
        params: {
          query: {
            limit: query.limit,
            ...(query.sourceKey === null ? {} : { source_key: query.sourceKey }),
            ...(query.status === null ? {} : { status: query.status }),
            ...(query.trigger === null ? {} : { trigger: query.trigger }),
            ...(query.cursor === null ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => pageFromDto(body, crawlRunFromDto));
  }

  async documents(
    key: string,
    cursor: string | null,
    limit: number,
  ): Promise<Result<Page<StoredDocument>>> {
    const result = await call(
      this.pipeline.GET("/v1/pipeline/sources/{key}/documents", {
        params: {
          path: { key },
          query: { limit, ...(cursor === null ? {} : { cursor }) },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => pageFromDto(body, storedDocumentFromDto));
  }
}

/** The gateway for the source pages; tests add fetchImpl. */
export function sourcesGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): SourcesGateway {
  return new SourcesGateway(ctx);
}
