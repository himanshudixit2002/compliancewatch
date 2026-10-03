import { livePageHref } from "@/shared/config/screens";

/**
 * The services summary on the admin home: how many services answer their health check, and
 * which ones do not, with the address probed and the reason. The system page, once built, shows
 * every probe in full; the summary links to it then.
 */
export interface ProbeLike {
  service: string;
  baseUrl: string;
  state: "up" | "down";
  reason?: string;
}

export interface DownService {
  service: string;
  baseUrl: string;
  reason: string;
}

export interface ServicesSummaryView {
  up: number;
  total: number;
  down: DownService[];
  /** The system page, once it is built. */
  systemHref: string | null;
}

export const SYSTEM_ROUTE = "/admin/system";

export function servicesSummary(
  probes: readonly ProbeLike[],
  hrefOf: (route: string) => string | null = livePageHref,
): ServicesSummaryView {
  const down = probes
    .filter((probe) => probe.state === "down")
    .map((probe) => ({
      service: probe.service,
      baseUrl: probe.baseUrl,
      reason: probe.reason ?? "unreachable",
    }));
  return {
    up: probes.length - down.length,
    total: probes.length,
    down,
    systemHref: hrefOf(SYSTEM_ROUTE),
  };
}
