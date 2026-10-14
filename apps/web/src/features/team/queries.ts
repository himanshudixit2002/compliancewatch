import "server-only";

import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import type { Result } from "@/server/result";
import { teamGateway } from "./gateway";
import type { TeamMember } from "./model/team";

/** The team page's read: the tenant's users, as identity lists them. */
export async function getTeam(
  session: ClientPrincipal,
  deps: { fetchImpl?: ClientContext["fetchImpl"] } = {},
): Promise<Result<TeamMember[]>> {
  return teamGateway({ session, fetchImpl: deps.fetchImpl }).list();
}
