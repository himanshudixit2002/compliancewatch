import "server-only";

import { documentDetailFromDto } from "@/entities/pipeline/mappers";
import type { DocumentDetail } from "@/entities/pipeline/types";
import { documentFromDto, relationCandidateFromDto } from "@/entities/rulebook/mappers";
import type { RelationCandidate, RulebookDocument } from "@/entities/rulebook/types";
import {
  reviewStatsFromDto,
  reviewTaskDetailFromDto,
  ruleFromDto,
  ruleVersionFromDto,
  taskPageFromDto,
} from "@/entities/rule-version/mappers";
import type {
  ReviewStats,
  ReviewTaskDetail,
  RuleSummary,
  RuleVersion,
  TaskPage,
} from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import {
  pipelineClient,
  rulebookClient,
  type ClientContext,
  type PipelineClient,
  type RulebookClient,
} from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { ReviewTasksPort, TaskQuery } from "./ports";

/** The most relation candidates the rulebook lists in one page, and so the most a draft offers. */
export const RELATIONS_LIMIT = 200;

/**
 * The review screens over the typed rulebook client, with no tenant header and no token, and the
 * pipeline's record of a stored document. The queue, a task, the stats, the relation candidates
 * and the versions are read fresh: the pipeline opens tasks and analysts decide them outside this
 * server. A document never changes under its id and the rule list is a global registry, so both
 * are cached under their tags (D-018).
 */
export class ReviewTasksGateway implements ReviewTasksPort {
  private readonly rulebook: RulebookClient;
  private readonly pipeline: PipelineClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
    this.pipeline = pipelineClient(ctx);
  }

  async tasks(query: TaskQuery): Promise<Result<TaskPage>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/tasks", {
        params: {
          query: {
            limit: query.limit,
            ...(query.status === null ? {} : { status: query.status }),
            ...(query.regulator === null ? {} : { regulator: query.regulator }),
            ...(query.kind === null ? {} : { kind: query.kind }),
            ...(query.cursor === null ? {} : { cursor: query.cursor }),
          },
        },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, taskPageFromDto);
  }

  async task(taskId: string): Promise<Result<ReviewTaskDetail>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/tasks/{task_id}", {
        params: { path: { task_id: taskId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, reviewTaskDetailFromDto);
  }

  async stats(): Promise<Result<ReviewStats>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/stats", { ...uncachedRead() }),
    );
    return mapBody(result, reviewStatsFromDto);
  }

  async document(documentId: string): Promise<Result<RulebookDocument>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/documents/{document_id}", {
        params: { path: { document_id: documentId } },
        ...cachedRead([tags.rulebook.document(documentId)]),
      }),
    );
    return mapBody(result, documentFromDto);
  }

  async storedDocument(documentId: string): Promise<Result<DocumentDetail>> {
    const result = await call(
      this.pipeline.GET("/v1/pipeline/documents/{document_id}", {
        params: { path: { document_id: documentId } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, documentDetailFromDto);
  }

  async openRelations(documentId: string): Promise<Result<RelationCandidate[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/relations", {
        params: { query: { status: "open", document_id: documentId, limit: RELATIONS_LIMIT } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (candidates) => candidates.map(relationCandidateFromDto));
  }

  async rules(): Promise<Result<RuleSummary[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rules", { ...cachedRead([tags.rulebook.rules()]) }),
    );
    return mapBody(result, (rules) => rules.map(ruleFromDto));
  }

  async versionsOf(ruleKey: string): Promise<Result<RuleVersion[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rules/{rule_key}/versions", {
        params: { path: { rule_key: ruleKey } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (versions) => versions.map(ruleVersionFromDto));
  }
}

/** The gateway for the review pages and actions; tests add fetchImpl. */
export function reviewTasksGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): ReviewTasksGateway {
  return new ReviewTasksGateway(ctx);
}
