import "server-only";

import { randomUUID } from "node:crypto";
import { SERVICE_NAMES, type ServiceName } from "@/shared/config/services";
import { REQUEST_ID_HEADER, type FetchImpl } from "./api/client";
import { getEnv, serviceUrl } from "./env";

/**
 * Liveness probes of the services, for the internal tools: `GET /health` on each base URL the
 * environment names, server-side, without a tenant header or a token (py-common mounts the
 * route at every service's root and answers `{status: "ok", service, version}`). Each probe has
 * its own time limit and never throws: a refused connection, a timeout, an error status or a
 * body that is not the health shape is a "down" answer with the reason, so one stopped service
 * never fails the page that asks. The probes of all ten services run in parallel.
 */
export const HEALTH_PATH = "/health";

/** How long one probe waits; a slower service counts as down. */
export const HEALTH_TIMEOUT_MS = 2_000;

export type ProbeState = "up" | "down";

export interface HealthProbe {
  service: ServiceName;
  /** The base URL probed, from CW_WEB_<SERVICE>_URL. */
  baseUrl: string;
  state: ProbeState;
  /** The HTTP status, when a response arrived. */
  status?: number;
  /** The version the service reports, when it answered. */
  version?: string;
  latencyMs: number;
  /** Why the probe counts as down. */
  reason?: string;
}

export interface ProbeOptions {
  fetchImpl?: FetchImpl;
  timeoutMs?: number;
  /** A clock in milliseconds, for tests. */
  now?: () => number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function failureReason(error: unknown, timeoutMs: number): string {
  if (error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError")) {
    return `no answer within ${timeoutMs} ms`;
  }
  return "unreachable";
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** One service's /health, answered as up or down with the reason; never throws. */
export async function probeHealth(
  service: ServiceName,
  options: ProbeOptions = {},
): Promise<HealthProbe> {
  const baseUrl = serviceUrl(service, getEnv());
  const timeoutMs = options.timeoutMs ?? HEALTH_TIMEOUT_MS;
  const now = options.now ?? Date.now;
  const fetchImpl: FetchImpl = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const started = now();
  const request = new Request(`${baseUrl}${HEALTH_PATH}`, {
    headers: { accept: "application/json", [REQUEST_ID_HEADER]: randomUUID() },
    cache: "no-store",
  });
  const down = (reason: string, status?: number): HealthProbe => ({
    service,
    baseUrl,
    state: "down",
    ...(status === undefined ? {} : { status }),
    latencyMs: Math.max(0, now() - started),
    reason,
  });
  let response: Response;
  try {
    response = await fetchImpl(request, {
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
  } catch (error) {
    return down(failureReason(error, timeoutMs));
  }
  const body = await readBody(response);
  if (!response.ok) return down(`HTTP ${response.status}`, response.status);
  if (!isRecord(body) || body.status !== "ok") {
    return down("the answer is not a health report", response.status);
  }
  return {
    service,
    baseUrl,
    state: "up",
    status: response.status,
    ...(typeof body.version === "string" ? { version: body.version } : {}),
    latencyMs: Math.max(0, now() - started),
  };
}

/** Every service's /health, in the Makefile's SERVICES order. */
export function probeAllHealth(options: ProbeOptions = {}): Promise<HealthProbe[]> {
  return Promise.all(SERVICE_NAMES.map((service) => probeHealth(service, options)));
}
