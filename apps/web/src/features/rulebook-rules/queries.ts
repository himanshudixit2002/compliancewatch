import "server-only";

import type { ClientContext } from "@/server/api/services";
import { mapResult, type Result } from "@/server/result";
import { rulesGateway } from "./gateway";
import { ruleRows } from "./model/rules";
import type { RuleRow } from "./ui/rules-shared";

/** The rule list's rows, from the cached rule read. */
export async function getRules(
  deps: { fetchImpl?: ClientContext["fetchImpl"] } = {},
): Promise<Result<RuleRow[]>> {
  return mapResult(await rulesGateway(deps).rules(), ruleRows);
}
