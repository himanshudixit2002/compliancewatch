import "server-only";

import { z } from "zod";
import { SERVICE_NAMES, type ServiceName } from "@/shared/config/services";

/**
 * The web app's configuration: every CW_WEB_* variable, validated with zod. Nothing is read at
 * import time. `getEnv()` parses `process.env` on its first call from a request, a server
 * action or a route handler and keeps the frozen result, so `next build` runs with an empty
 * environment and a bad value is reported, with the variable's name, at the first request.
 * `loadEnv(record)` is the same parse over an explicit record, for tests.
 *
 * The values never reach the browser: there is no NEXT_PUBLIC_* variable, and this module is
 * server-only. Service URLs default to the repository's canonical ports (the Makefile's SERVICES
 * order, identity 8001 to pipeline 8010); a second working copy sets its own in .env.local.
 * The session secret is optional here and required by `requireSessionSecret()` only where a
 * session is encrypted or decrypted, so the public pages and the build need none.
 */
export const WEB_ENVS = ["local", "test", "staging", "prod"] as const;

export type WebEnvName = (typeof WEB_ENVS)[number];

/** `fake` mints sessions locally; `supabase` is reserved until its adapter exists. */
export const AUTH_PROVIDER_NAMES = ["fake", "supabase"] as const;

export type AuthProviderName = (typeof AUTH_PROVIDER_NAMES)[number];

export type EnvRecord = Readonly<Record<string, string | undefined>>;

export class EnvError extends Error {
  override readonly name = "EnvError";
}

const DEFAULT_PORT_BASE = 8000;
const SESSION_SECRET_BYTES = 32;
const BASE64 = /^[A-Za-z0-9+/_-]+={0,2}$/;
const CIDR = /^[0-9a-fA-F.:]+(\/\d{1,3})?$/;

export function isWebEnvName(value: string): value is WebEnvName {
  return (WEB_ENVS as readonly string[]).includes(value);
}

/** http://localhost:8001 for identity ... :8010 for pipeline. */
export function defaultServiceUrl(service: ServiceName): string {
  return `http://localhost:${DEFAULT_PORT_BASE + SERVICE_NAMES.indexOf(service) + 1}`;
}

/** The 32 bytes behind a base64 secret, or null when the value is not that. */
export function decodeSessionSecret(value: string): Uint8Array | null {
  if (!BASE64.test(value)) return null;
  const bytes = Buffer.from(value, "base64");
  return bytes.length === SESSION_SECRET_BYTES ? new Uint8Array(bytes) : null;
}

const httpUrl = z.url({ protocol: /^https?$/ }).transform((value) => value.replace(/\/+$/, ""));
const positiveInt = z.coerce.number().int().positive();
const envBoolean = z
  .enum(["true", "false", "1", "0"])
  .transform((value) => value === "true" || value === "1");
const cidrList = z
  .string()
  .default("")
  .transform((value) =>
    value
      .split(",")
      .map((entry) => entry.trim())
      .filter((entry) => entry !== ""),
  )
  .pipe(z.array(z.string().regex(CIDR, { error: "expected an IP or CIDR such as 10.0.0.0/8" })));
const sessionSecret = z.string().refine((value) => decodeSessionSecret(value) !== null, {
  error: "must be 32 random bytes as base64 (openssl rand -base64 32)",
});

const schema = z
  .object({
    CW_WEB_ENV: z.enum(WEB_ENVS).default("local"),
    CW_WEB_AUTH_PROVIDER: z.enum(AUTH_PROVIDER_NAMES).optional(),
    CW_WEB_SESSION_SECRET: sessionSecret.optional(),
    CW_WEB_SESSION_TTL_SECONDS: positiveInt.max(86_400).default(28_800),
    CW_WEB_REQUEST_TIMEOUT_MS: positiveInt.max(120_000).default(10_000),
    // The two shared secrets (ADR-018). The write token is the rulebook's CW_RULEBOOK_WRITE_TOKEN,
    // which the pipeline reads as its own copy: server/api/rulebook-write.ts sends it to the
    // rulebook and server/api/pipeline-write.ts to the pipeline, for an admin's writes. The review
    // token opens the analyst's decisions, sent by server/api/rulebook-write.ts alone.
    CW_WEB_RULEBOOK_WRITE_TOKEN: z.string().min(1).optional(),
    CW_WEB_RULEBOOK_REVIEW_TOKEN: z.string().min(1).optional(),
    // The largest file the upload handler forwards to the pipeline: the pipeline's own
    // CW_PIPELINE_UPLOAD_MAX_BYTES, with the same default and ceiling (server/bff/upload.ts).
    CW_WEB_PIPELINE_UPLOAD_MAX_BYTES: positiveInt.max(100_000_000).default(25_000_000),
    CW_WEB_ADMIN_IP_ALLOWLIST: cidrList,
    // Trust the reverse proxy's forwarded headers: the client IP (x-real-ip, x-forwarded-for)
    // and, for the sign-out origin check, the host (x-forwarded-host).
    CW_WEB_TRUST_FORWARDED_IP: envBoolean.default(false),
    CW_WEB_SEED_STATE_PATH: z.string().min(1).default("../../var/seed/last.json"),
    CW_WEB_BUILD_SHA: z.string().min(1).optional(),
    CW_WEB_IDENTITY_URL: httpUrl.default(defaultServiceUrl("identity")),
    CW_WEB_PROFILE_URL: httpUrl.default(defaultServiceUrl("profile")),
    CW_WEB_RULEBOOK_URL: httpUrl.default(defaultServiceUrl("rulebook")),
    CW_WEB_APPLICABILITY_ENGINE_URL: httpUrl.default(defaultServiceUrl("applicability-engine")),
    CW_WEB_OBLIGATION_URL: httpUrl.default(defaultServiceUrl("obligation")),
    CW_WEB_NOTIFICATION_URL: httpUrl.default(defaultServiceUrl("notification")),
    CW_WEB_QA_URL: httpUrl.default(defaultServiceUrl("qa")),
    CW_WEB_LLM_GATEWAY_URL: httpUrl.default(defaultServiceUrl("llm-gateway")),
    CW_WEB_EVAL_URL: httpUrl.default(defaultServiceUrl("eval")),
    CW_WEB_PIPELINE_URL: httpUrl.default(defaultServiceUrl("pipeline")),
  })
  .superRefine((env, ctx) => {
    if (env.CW_WEB_AUTH_PROVIDER === "fake" && !isLocalOrTest(env.CW_WEB_ENV)) {
      ctx.addIssue({
        code: "custom",
        path: ["CW_WEB_AUTH_PROVIDER"],
        message: "fake is allowed only when CW_WEB_ENV is local or test",
      });
    }
  });

export type WebEnv = Readonly<z.output<typeof schema>>;

const SERVICE_URL_KEYS = {
  identity: "CW_WEB_IDENTITY_URL",
  profile: "CW_WEB_PROFILE_URL",
  rulebook: "CW_WEB_RULEBOOK_URL",
  "applicability-engine": "CW_WEB_APPLICABILITY_ENGINE_URL",
  obligation: "CW_WEB_OBLIGATION_URL",
  notification: "CW_WEB_NOTIFICATION_URL",
  qa: "CW_WEB_QA_URL",
  "llm-gateway": "CW_WEB_LLM_GATEWAY_URL",
  eval: "CW_WEB_EVAL_URL",
  pipeline: "CW_WEB_PIPELINE_URL",
} as const satisfies Record<ServiceName, keyof WebEnv>;

/** Parses a record; an empty value counts as unset. Throws EnvError naming each bad variable. */
export function loadEnv(record: EnvRecord): WebEnv {
  const input: Record<string, string> = {};
  for (const [key, value] of Object.entries(record)) {
    if (key.startsWith("CW_WEB_") && value !== undefined && value !== "") input[key] = value;
  }
  const parsed = schema.safeParse(input);
  if (!parsed.success) {
    const lines = parsed.error.issues.map(
      (issue) => `${issue.path.map(String).join(".") || "environment"}: ${issue.message}`,
    );
    throw new EnvError(`invalid web environment: ${lines.join("; ")}`);
  }
  const env = parsed.data;
  Object.freeze(env.CW_WEB_ADMIN_IP_ALLOWLIST);
  return Object.freeze(env);
}

let cached: WebEnv | undefined;

/** The process environment, parsed on the first call and kept. */
export function getEnv(): WebEnv {
  cached ??= loadEnv(process.env);
  return cached;
}

/** Forgets the parsed environment so the next `getEnv()` reads `process.env` again (tests). */
export function resetEnvCache(): void {
  cached = undefined;
}

export function webEnvName(env: WebEnv = getEnv()): WebEnvName {
  return env.CW_WEB_ENV;
}

/** Local-only pages (the design catalogue, the fake sign-in) exist only in these two. */
export function isLocalOrTest(name: WebEnvName = getEnv().CW_WEB_ENV): boolean {
  return name === "local" || name === "test";
}

export function serviceUrl(service: ServiceName, env: WebEnv = getEnv()): string {
  return env[SERVICE_URL_KEYS[service]];
}

/** The session key; throws EnvError when CW_WEB_SESSION_SECRET is unset. */
export function requireSessionSecret(env: WebEnv = getEnv()): Uint8Array {
  const value = env.CW_WEB_SESSION_SECRET;
  const bytes = value === undefined ? null : decodeSessionSecret(value);
  if (bytes === null) {
    throw new EnvError(
      "CW_WEB_SESSION_SECRET is required to encrypt or decrypt a session:" +
        " set 32 random bytes as base64 (openssl rand -base64 32)",
    );
  }
  return bytes;
}
