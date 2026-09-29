/**
 * Feature flags declared as data. Every flag defaults to off, names an owner and a removal
 * condition, and is read only through the server-side flag reader (never from the browser).
 * The env override CW_WEB_FLAG_<NAME>=true (name upper-cased, dots as underscores) is honoured
 * only when CW_WEB_ENV is local or test. When the shared flag registry package exists, these
 * declarations move there and this file keeps the typed name list.
 */
export type FlagOwner =
  "core-product" | "platform" | "regulatory-intelligence" | "ai-platform" | "identity-partner";

export interface FlagDeclaration {
  name: string;
  owner: FlagOwner;
  default: false;
  /** When the flag goes away, in plain words. */
  removal: string;
  description: string;
}

export const FLAGS = [
  {
    name: "web.analytics_enabled",
    owner: "core-product",
    default: false,
    removal: "When counsel has confirmed the analytics consent purpose and events run everywhere.",
    description:
      "Product events (JSON lines and span events) for sessions that granted the analytics consent.",
  },
  {
    name: "web.otel_enabled",
    owner: "platform",
    default: false,
    removal: "When OTLP export runs in every environment.",
    description: "Registers OpenTelemetry in instrumentation.ts and exports spans over OTLP HTTP.",
  },
  {
    name: "web.admin_rulebook_writes",
    owner: "regulatory-intelligence",
    default: false,
    removal: "When the rulebook write routes take a bearer token and no shared token remains.",
    description: "Entity and relation decisions from /admin through the server-side write token.",
  },
  {
    name: "web.qa_enabled",
    owner: "ai-platform",
    default: false,
    removal: "When the qa ask route is on for every tenant.",
    description: "The ask screen on the qa ask route.",
  },
  {
    name: "web.publish_actions",
    owner: "regulatory-intelligence",
    default: false,
    removal: "When the publish workflow has run in staging for a release cycle.",
    description: "Submit, return, approve, publish and withdraw on the rule version detail.",
  },
  {
    name: "web.tenant_header_off",
    owner: "identity-partner",
    default: false,
    removal: "When every service runs token mode and the tenant header is gone.",
    description: "Stops sending x-tenant-id once services take the tenant from the bearer token.",
  },
] as const satisfies readonly FlagDeclaration[];

export type FlagName = (typeof FLAGS)[number]["name"];

export const FLAG_NAMES = FLAGS.map((flag) => flag.name) as readonly FlagName[];

export function isFlagName(value: string): value is FlagName {
  return (FLAG_NAMES as readonly string[]).includes(value);
}

/** The environment variable that overrides a flag in local and test: web.qa_enabled -> CW_WEB_FLAG_QA_ENABLED. */
export function envVarFor(name: FlagName): string {
  return `CW_WEB_FLAG_${name.replace(/^web\./, "").toUpperCase()}`;
}
