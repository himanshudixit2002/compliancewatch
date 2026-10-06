import "server-only";

import { ruleFromDto } from "@/entities/rule-version/mappers";
import type { RuleSummary } from "@/entities/rule-version/types";
import { call } from "@/server/api/client";
import { rulebookClient, type ClientContext, type RulebookClient } from "@/server/api/services";
import { cachedRead, tags } from "@/server/cache";
import { mapBody, type Result } from "@/server/result";
import type { RulesPort } from "./ports";

/**
 * The rules over the typed rulebook client: a global registry, the same for every tenant, kept
 * for five minutes under `rulebook:rules` like the admin home's count of it (D-018). No tenant
 * header and no token.
 */
export class RulesGateway implements RulesPort {
  private readonly rulebook: RulebookClient;

  constructor(ctx: Pick<ClientContext, "fetchImpl">) {
    this.rulebook = rulebookClient(ctx);
  }

  async rules(): Promise<Result<RuleSummary[]>> {
    const result = await call(
      this.rulebook.GET("/v1/rulebook/rules", { ...cachedRead([tags.rulebook.rules()]) }),
    );
    return mapBody(result, (rules) => rules.map(ruleFromDto));
  }
}

/** The gateway for the rule list; tests add fetchImpl. */
export function rulesGateway(ctx: Pick<ClientContext, "fetchImpl"> = {}): RulesGateway {
  return new RulesGateway(ctx);
}
