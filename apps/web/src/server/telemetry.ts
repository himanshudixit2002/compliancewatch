import "server-only";

import type { Configuration } from "@vercel/otel";
import type { FlagName } from "@/shared/config/flags";
import { isEnabled } from "./flags";
import { RedactingSpanProcessor } from "./telemetry-redaction";

/**
 * OpenTelemetry for the web server, behind the flag `web.otel_enabled` (off by default, owned by
 * platform). `instrumentation.ts` calls `registerTelemetry()` once when a Node.js server starts:
 * with the flag off nothing is loaded and nothing registers, so the app runs without a tracer as
 * before. With it on, `@vercel/otel` registers a tracer provider (Next.js's own spans, the fetch
 * instrumentation, and the `product.*` span events of server/analytics.ts), and spans leave the
 * process only when an OTLP endpoint is configured (`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` or
 * `OTEL_EXPORTER_OTLP_ENDPOINT`, OTLP over HTTP; protocol and headers from the standard OTLP
 * variables). Without one no span processor is installed: `@vercel/otel`'s default would export
 * to localhost:4318 whether or not a collector listens there, which is not what "off unless
 * configured" means. With one, the redacting processor (server/telemetry-redaction.ts) runs ahead
 * of the exporting ones, so no URL leaves with its query or a segment that names a person. A
 * failure here is logged as one line and never stops the server.
 */
export const OTEL_FLAG: FlagName = "web.otel_enabled";

/** The service name spans carry (OTEL_SERVICE_NAME overrides it, as @vercel/otel reads it). */
export const SERVICE_NAME = "compliancewatch-web";

const ENDPOINT_VARIABLES = ["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_ENDPOINT"];

type Environment = Readonly<Record<string, string | undefined>>;

/** True when the environment names an OTLP endpoint for traces. */
export function otlpEndpointConfigured(env: Environment = process.env): boolean {
  return ENDPOINT_VARIABLES.some((name) => (env[name] ?? "").trim() !== "");
}

export interface TelemetryPlan {
  /** The flag is on, so a tracer provider registers. */
  enabled: boolean;
  /** Spans are exported: the flag is on and an OTLP endpoint is configured. */
  exporting: boolean;
}

/** What registration does on this server, from the flag (no tenant) and the environment. */
export async function telemetryPlan(env: Environment = process.env): Promise<TelemetryPlan> {
  const enabled = await isEnabled(OTEL_FLAG);
  return { enabled, exporting: enabled && otlpEndpointConfigured(env) };
}

/**
 * The @vercel/otel configuration for a plan: no span processor without an endpoint; with one, the
 * redacting processor first and then the exporting ones @vercel/otel builds ("auto").
 */
export function otelConfiguration(plan: TelemetryPlan): Configuration {
  return {
    serviceName: SERVICE_NAME,
    spanProcessors: plan.exporting ? [new RedactingSpanProcessor(), "auto"] : [],
  };
}

export type Register = (configuration: Configuration) => void;

async function vercelRegister(): Promise<Register> {
  const { registerOTel } = await import("@vercel/otel");
  return registerOTel;
}

/** What registration did: the plan it carried out, or that it failed and nothing registered. */
export type TelemetryOutcome = TelemetryPlan & { failed?: true };

/**
 * Where the outcome is kept for the life of the process. `instrumentation.ts` and the app's pages
 * are separate bundles, each with its own copy of this module, in one Node.js process, so a
 * module variable set at startup is not the one a page reads; `globalThis` is shared.
 */
const REGISTRATION: unique symbol = Symbol.for("compliancewatch.web.telemetry");

type Holder = typeof globalThis & { [REGISTRATION]?: TelemetryOutcome };

function remember(outcome: TelemetryOutcome): TelemetryOutcome {
  (globalThis as Holder)[REGISTRATION] = outcome;
  return outcome;
}

/**
 * What registration did when this server started, or null when it has not run here (the edge
 * runtime, a unit test). The system page shows this rather than asking the flag again: the flag is
 * read once, and a change to it takes effect when the server restarts.
 */
export function registeredTelemetry(): TelemetryOutcome | null {
  return (globalThis as Holder)[REGISTRATION] ?? null;
}

/** Forgets the outcome, so a test starts as a server that has not registered. */
export function resetTelemetryRegistration(): void {
  delete (globalThis as Holder)[REGISTRATION];
}

/**
 * Registers OpenTelemetry when the flag is on, keeps what it did for the system page, and returns
 * it. `load` gives the register function (tests pass their own); it is only loaded when the flag
 * is on.
 */
export async function registerTelemetry(
  load: () => Promise<Register> = vercelRegister,
  env: Environment = process.env,
): Promise<TelemetryOutcome> {
  try {
    const plan = await telemetryPlan(env);
    if (!plan.enabled) return remember(plan);
    const register = await load();
    register(otelConfiguration(plan));
    console.info(
      JSON.stringify({ level: "info", event: "telemetry_registered", exporting: plan.exporting }),
    );
    return remember(plan);
  } catch (error) {
    console.warn(
      JSON.stringify({
        level: "warn",
        event: "telemetry_registration_failed",
        error: error instanceof Error ? error.message : String(error),
      }),
    );
    return remember({ enabled: false, exporting: false, failed: true });
  }
}
