import "server-only";

import type { ClientContext } from "@/server/api/services";
import { isEnabled } from "@/server/flags";
import { ok, type Result } from "@/server/result";
import { nodeOptions, type NodeOption } from "./model/ask";
import { askGateway } from "./gateway";

/**
 * The ask page's read: whether asking is on for the session's tenant (`web.qa_enabled`), and the
 * business with the nodes a question can be about. Nothing is asked of the qa service until the
 * person asks.
 */
export interface QueryDeps {
  fetchImpl?: ClientContext["fetchImpl"];
}

export type QuerySession = NonNullable<ClientContext["session"]>;

export const QA_FLAG = "web.qa_enabled" as const;

export interface AskPageView {
  business: { id: string; name: string; pan: string };
  enabled: boolean;
  nodes: readonly NodeOption[];
}

export async function getAskPage(
  session: QuerySession,
  businessId: string,
  deps: QueryDeps = {},
): Promise<Result<AskPageView>> {
  const [business, enabled] = await Promise.all([
    askGateway({ session, fetchImpl: deps.fetchImpl }).business(businessId),
    isEnabled(QA_FLAG, { tenantId: session.tenantId }),
  ]);
  if (!business.ok) return business;
  return ok({
    business: { id: business.value.id, name: business.value.name, pan: business.value.pan },
    enabled,
    nodes: nodeOptions(business.value),
  });
}
