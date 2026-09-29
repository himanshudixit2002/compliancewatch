import "server-only";

import { call } from "@/server/api/client";
import {
  llmGatewayClient,
  rulebookClient,
  type ClientContext,
  type LlmGatewayClient,
  type RulebookClient,
} from "@/server/api/services";
import { cachedRead, tags, uncachedRead } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { AdminCountsPort, ListCount } from "./ports";

/**
 * The largest page the review queues serve (`limit` is at most 200 on both routes); a count
 * that fills it is shown as "200+". No route counts a queue, so this reads one page.
 */
export const COUNT_PAGE = 200;

function countOf(rows: readonly unknown[], pageSize?: number): ListCount {
  return { count: rows.length, capped: pageSize !== undefined && rows.length >= pageSize };
}

/**
 * The admin home's counts over the typed rulebook and llm-gateway clients. The review queues are
 * read fresh on every visit (the pipeline fills them, outside this app, so a cached page would
 * lag behind it); the rules and the prompts are global registries kept under their tags for five
 * minutes, like the pages that list them.
 */
export class AdminCountsGateway implements AdminCountsPort {
  private readonly rulebook: RulebookClient;
  private readonly llm: LlmGatewayClient;

  constructor(ctx: ClientContext) {
    this.rulebook = rulebookClient(ctx);
    this.llm = llmGatewayClient(ctx);
  }

  async entityGroups(): Promise<Result<ListCount>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/entities", {
        params: { query: { limit: COUNT_PAGE } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (groups) => ({
      ...countOf(groups, COUNT_PAGE),
      within: groups.reduce((sum, group) => sum + group.open_count, 0),
    }));
  }

  async openRelationCandidates(): Promise<Result<ListCount>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/review/relations", {
        params: { query: { status: "open", limit: COUNT_PAGE } },
        ...uncachedRead(),
      }),
    );
    return mapBody(result, (candidates) => countOf(candidates, COUNT_PAGE));
  }

  async rules(): Promise<Result<ListCount>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rules", { ...cachedRead([tags.rulebook.rules()]) }),
    );
    return mapBody(result, (rules) => countOf(rules));
  }

  async prompts(): Promise<Result<ListCount>> {
    const result = await call(
      this.llm.GET("/v1/llm-gateway/prompts", { ...cachedRead([tags.llm.prompts()]) }),
    );
    return mapBody(result, (prompts) => countOf(prompts));
  }
}

/** The gateway for the admin home; tests add fetchImpl. */
export function adminCountsGateway(ctx: ClientContext): AdminCountsGateway {
  return new AdminCountsGateway(ctx);
}
