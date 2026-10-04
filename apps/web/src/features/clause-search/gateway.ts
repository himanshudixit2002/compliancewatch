import "server-only";

import { searchHitFromDto, searchToDto } from "@/entities/rulebook/mappers";
import type { SearchHit, SearchQuery } from "@/entities/rulebook/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { mapBody, type Result } from "@/server/result";
import type { SearchPort } from "./ports";

/**
 * `POST /v1/rulebook/search` over the typed client, with no tenant header and no token. The
 * query travels in the POST body only. The web app sends the words without an embedding, so the
 * rulebook runs its full-text leg alone (the vector leg needs a query vector from the model the
 * clauses were embedded with, which the LLM gateway makes and this page does not ask for).
 */
export class SearchGateway implements SearchPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async search(query: SearchQuery): Promise<Result<readonly SearchHit[]>> {
    const result = await call(
      this.rulebook.POST("/v1/rulebook/search", { body: searchToDto(query) }),
    );
    return mapBody(result, (body) => body.map(searchHitFromDto));
  }
}

/** The gateway for an action; tests add fetchImpl. */
export function searchGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): SearchGateway {
  return new SearchGateway(ctx);
}
