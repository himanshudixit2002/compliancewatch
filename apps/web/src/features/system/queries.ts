import "server-only";

import type { ClientContext } from "@/server/api/services";
import { getEnv } from "@/server/env";
import { flagProviderStatus } from "@/server/flags";
import { HEALTH_TIMEOUT_MS, probeAllHealth, probeAllReady } from "@/server/health";
import { telemetryPlan } from "@/server/telemetry";
import { systemRows, type ServiceRow, type SystemSummary } from "./model/system";
import type { WebFacts } from "./ui/system-shared";

/**
 * The system page's read: every service's /health and /ready probed from the web server in
 * parallel (twenty probes, two seconds each at most, no tenant header and no token), the
 * registry's facts per service, and the web server's own configuration as plain facts. A
 * secret's value never leaves this module: a token is only said to be set or not.
 */
export interface SystemView {
  rows: ServiceRow[];
  summary: SystemSummary;
  facts: WebFacts;
  probeTimeoutSeconds: number;
}

export async function getSystem(
  deps: { fetchImpl?: ClientContext["fetchImpl"]; env?: Record<string, string | undefined> } = {},
): Promise<SystemView> {
  const [health, ready, flags, telemetry] = await Promise.all([
    probeAllHealth({ fetchImpl: deps.fetchImpl }),
    probeAllReady({ fetchImpl: deps.fetchImpl }),
    flagProviderStatus(),
    telemetryPlan(deps.env ?? process.env),
  ]);
  const env = getEnv();
  const { rows, summary } = systemRows(health, ready);
  return {
    rows,
    summary,
    probeTimeoutSeconds: HEALTH_TIMEOUT_MS / 1000,
    facts: {
      environment: env.CW_WEB_ENV,
      authProvider: env.CW_WEB_AUTH_PROVIDER ?? null,
      build: env.CW_WEB_BUILD_SHA ?? null,
      requestTimeoutMs: env.CW_WEB_REQUEST_TIMEOUT_MS,
      writeToken: env.CW_WEB_RULEBOOK_WRITE_TOKEN !== undefined,
      reviewToken: env.CW_WEB_RULEBOOK_REVIEW_TOKEN !== undefined,
      flagProvider: flags.ok
        ? { ok: true, name: flags.provider }
        : { ok: false, reason: flags.reason },
      telemetry,
      node: process.version,
    },
  };
}
