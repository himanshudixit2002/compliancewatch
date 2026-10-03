import "server-only";

import type { ClientContext, ClientPrincipal } from "@/server/api/services";
import { probeAllHealth } from "@/server/health";
import type { Result } from "@/server/result";
import { adminCountsGateway } from "./gateway";
import { COUNT_TILES, toCountTile, type CountTileKey, type CountTileView } from "./model/counts";
import { servicesSummary, type ServicesSummaryView } from "./model/services";
import type { ListCount } from "./ports";

/** The admin home's live part: the count tiles and the services summary. */
export interface AdminHomeData {
  tiles: CountTileView[];
  services: ServicesSummaryView;
}

/**
 * Reads the four counts and probes every service's /health, all at once. Nothing here fails
 * the page: a failed count becomes that tile's error and a stopped service a "down" line, so the
 * home still renders when one service is away.
 */
export async function getAdminHome(
  session: ClientPrincipal,
  deps: { fetchImpl?: ClientContext["fetchImpl"] } = {},
): Promise<AdminHomeData> {
  const gateway = adminCountsGateway({ session, fetchImpl: deps.fetchImpl });
  const reads: Record<CountTileKey, Promise<Result<ListCount>>> = {
    entityGroups: gateway.entityGroups(),
    relationCandidates: gateway.openRelationCandidates(),
    rules: gateway.rules(),
    prompts: gateway.prompts(),
  };
  const [counts, probes] = await Promise.all([
    Promise.all(COUNT_TILES.map((tile) => reads[tile.key])),
    probeAllHealth({ fetchImpl: deps.fetchImpl }),
  ]);
  return {
    tiles: COUNT_TILES.map((tile, index) => toCountTile(tile, counts[index] as Result<ListCount>)),
    services: servicesSummary(probes),
  };
}
