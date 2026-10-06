import { toAwaitedItem } from "@/entities/screen/mappers";
import type { AwaitedItemView } from "@/entities/screen/types";
import { SCREENS, hrefFor, routeParams, type Screen } from "@/shared/config/screens";
import { SERVICE_NAMES, routeKey, type ServiceName } from "@/shared/config/services";
import { t } from "@/shared/i18n";

/**
 * The system page's model: each service's liveness and readiness as the web server probed them,
 * and what the screen registry says about the service (the built screens that call it, the
 * routes screens still wait for from it). The probes come in as plain data, so this module stays
 * pure; the registry is read from the shared config.
 */
export interface HealthLike {
  service: string;
  baseUrl: string;
  state: "up" | "down";
  status?: number;
  version?: string;
  latencyMs: number;
  reason?: string;
}

export interface ReadyLike {
  service: string;
  state: "ready" | "not_ready" | "down";
  status?: number;
  checks: Readonly<Record<string, boolean>>;
  latencyMs: number;
  reason?: string;
}

export interface ScreenLink {
  id: string;
  title: string;
  /** The page, when its route has no parameters. */
  href: string | null;
}

export interface RegistryFacts {
  /** The live pages, handlers and parts that call the service. */
  liveScreens: ScreenLink[];
  /** Distinct routes screens still wait for from the service, with who delivers them. */
  awaited: AwaitedItemView[];
}

export interface ServiceRow {
  service: ServiceName;
  baseUrl: string;
  up: boolean;
  healthLabel: string;
  version: string | null;
  latency: string;
  ready: "ready" | "not_ready" | "down";
  readyLabel: string;
  checks: readonly { name: string; passed: boolean }[];
  /** Why a probe counts as down, liveness first. */
  reason: string | null;
  registry: RegistryFacts;
}

export interface SystemSummary {
  total: number;
  up: number;
  ready: number;
}

function link(screen: Screen): ScreenLink {
  return {
    id: screen.id,
    title: screen.title,
    href: screen.kind === "page" && routeParams(screen.route).length === 0 ? hrefFor(screen) : null,
  };
}

/** What the registry says about one service. */
export function registryFacts(
  service: ServiceName,
  screens: readonly Screen[] = SCREENS,
): RegistryFacts {
  const liveScreens = screens
    .filter(
      (screen) =>
        screen.status === "live" && screen.uses.some((route) => route.service === service),
    )
    .map(link);
  const awaited = new Map<string, AwaitedItemView>();
  for (const screen of screens) {
    for (const route of screen.awaits) {
      if (route.service !== service) continue;
      const key = routeKey(route);
      if (!awaited.has(key)) awaited.set(key, toAwaitedItem(route));
    }
  }
  return {
    liveScreens: liveScreens.sort((a, b) => a.title.localeCompare(b.title)),
    awaited: [...awaited.values()].sort(
      (a, b) => a.path.localeCompare(b.path) || a.method.localeCompare(b.method),
    ),
  };
}

const READY_LABELS = {
  ready: () => t("system.ready"),
  not_ready: () => t("system.notReady"),
  down: () => t("system.readyUnknown"),
} as const;

export function serviceRow(
  health: HealthLike,
  ready: ReadyLike,
  screens: readonly Screen[] = SCREENS,
): ServiceRow {
  const service = health.service as ServiceName;
  return {
    service,
    baseUrl: health.baseUrl,
    up: health.state === "up",
    healthLabel: health.state === "up" ? t("system.up") : t("system.down"),
    version: health.version ?? null,
    latency: t("system.latency", { ms: health.latencyMs }),
    ready: ready.state,
    readyLabel: READY_LABELS[ready.state](),
    checks: Object.entries(ready.checks)
      .map(([name, passed]) => ({ name, passed }))
      .sort((a, b) => a.name.localeCompare(b.name)),
    reason: health.reason ?? ready.reason ?? null,
    registry: registryFacts(service, screens),
  };
}

/** The rows in the Makefile's SERVICES order, and how many are up and ready. */
export function systemRows(
  health: readonly HealthLike[],
  ready: readonly ReadyLike[],
  screens: readonly Screen[] = SCREENS,
): { rows: ServiceRow[]; summary: SystemSummary } {
  const rows = SERVICE_NAMES.flatMap((service) => {
    const live = health.find((probe) => probe.service === service);
    const readiness = ready.find((probe) => probe.service === service);
    return live === undefined || readiness === undefined
      ? []
      : [serviceRow(live, readiness, screens)];
  });
  return {
    rows,
    summary: {
      total: rows.length,
      up: rows.filter((row) => row.up).length,
      ready: rows.filter((row) => row.ready === "ready").length,
    },
  };
}
