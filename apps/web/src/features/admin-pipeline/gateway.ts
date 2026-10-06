import "server-only";

import {
  crawlRunFromDto,
  documentDetailFromDto,
  outboxEventFromDto,
  pageFromDto,
  pipelineDocumentFromDto,
  taskFromDto,
} from "@/entities/pipeline/mappers";
import type {
  CrawlRun,
  DocumentDetail,
  OutboxEvent,
  Page,
  PipelineDocument,
  PipelineTask,
} from "@/entities/pipeline/types";
import { call } from "@/server/api/client";
import { pipelineClient, type ClientContext, type PipelineClient } from "@/server/api/services";
import { uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { DeadEventQuery, DocumentQuery, PipelinePort, RunQuery, TaskQuery } from "./ports";

/**
 * The pipeline pages over the typed pipeline client, with no tenant header and no token. Nothing
 * is cached: crawls, ingests, the relay and people's retries, requeues and resolutions move these
 * records outside this server.
 */
export class PipelineGateway implements PipelinePort {
  private readonly pipeline: PipelineClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.pipeline = pipelineClient(ctx);
  }

  async runs(query: RunQuery): Promise<Result<Page<CrawlRun>>> {
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

  async documents(query: DocumentQuery): Promise<Result<Page<PipelineDocument>>> {
    const result = await call(
      this.pipeline.GET("/v1/pipeline/documents", {
        params: {
          query: {
            limit: query.limit,
            ...(query.status === null ? {} : { status: query.status }),
            ...(query.sourceKey === null ? {} : { source_key: query.sourceKey }),
            ...(query.docType === null ? {} : { doc_type: query.docType }),
            ...(query.publishedFrom === null ? {} : { published_from: query.publishedFrom }),
            ...(query.publishedTo === null ? {} : { published_to: query.publishedTo }),
            ...(query.cursor === null ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => pageFromDto(body, pipelineDocumentFromDto));
  }

  async document(documentId: string): Promise<Result<DocumentDetail>> {
    const result = await call(
      this.pipeline.GET("/v1/pipeline/documents/{document_id}", {
        params: { path: { document_id: documentId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, documentDetailFromDto);
  }

  async deadEvents(query: DeadEventQuery): Promise<Result<Page<OutboxEvent>>> {
    const result = await call(
      this.pipeline.GET("/v1/pipeline/outbox/dead", {
        params: {
          query: {
            limit: query.limit,
            ...(query.topic === null ? {} : { topic: query.topic }),
            ...(query.cursor === null ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => pageFromDto(body, outboxEventFromDto));
  }

  async tasks(query: TaskQuery): Promise<Result<Page<PipelineTask>>> {
    const result = await call(
      this.pipeline.GET("/v1/pipeline/tasks", {
        params: {
          query: {
            limit: query.limit,
            ...(query.status === null ? {} : { status: query.status }),
            ...(query.kind === null ? {} : { kind: query.kind }),
            ...(query.cursor === null ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (body) => pageFromDto(body, taskFromDto));
  }

  async sourceKeys(): Promise<Result<string[]>> {
    const result = await call(this.pipeline.GET("/v1/pipeline/sources", { ...uncachedRead() }));
    return mapBody(result, (body) => body.items.map((source) => source.key));
  }
}

/** The gateway for the pipeline pages; tests add fetchImpl. */
export function pipelineGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): PipelineGateway {
  return new PipelineGateway(ctx);
}
