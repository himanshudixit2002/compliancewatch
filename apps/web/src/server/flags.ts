import "server-only";

import {
  configureFlags,
  isEnabled as registryIsEnabled,
  resetFlags,
  type Environment,
  type FlagLog,
} from "@compliancewatch/flags/server";
import { overrideEnv } from "@compliancewatch/flags";
import { FLAG_NAMES, envVarFor, type FlagName } from "@/shared/config/flags";
import { getEnv, isLocalOrTest, type WebEnvName } from "./env";

/**
 * The web app's flag reader: the one place a page, an action or a server module asks whether a
 * web flag is on. It answers through `@compliancewatch/flags/server` (the registry's
 * OpenFeature client), configured once per server process on the first question, with the
 * provider `CW_FLAGS_PROVIDER` names (env by default, or Unleash).
 *
 * The env provider reads a web flag's override variable, `CW_WEB_FLAG_<NAME>` (the entry's
 * `env`), or the SDK's generic `CW_FLAG_WEB_<NAME>`. Those overrides are honoured only when
 * CW_WEB_ENV is local or test: in staging and prod they are removed from what the provider
 * reads, so a stray variable cannot switch a flag on there, and a flag is turned on through
 * Unleash instead. Every web flag defaults to off.
 *
 * Nothing here reaches the browser: a page asks on the server and renders the outcome. A
 * provider that cannot be configured (Unleash chosen without its URL, say) answers off for
 * every flag, logs one JSON line, and is tried again on the next question.
 */
export interface FlagTarget {
  /** The tenant the flag is evaluated for, when the flag targets tenants. */
  tenantId?: string;
}

const WEB_OVERRIDES: ReadonlySet<string> = new Set(
  FLAG_NAMES.flatMap((name) => [envVarFor(name), overrideEnv(name)]),
);

function isWebOverride(variable: string): boolean {
  if (WEB_OVERRIDES.has(variable)) return true;
  // A tenant allow-list of a web flag: CW_FLAG_WEB_<NAME>__TENANTS.
  return FLAG_NAMES.some((name) => variable.startsWith(`${overrideEnv(name)}__`));
}

/** What the provider reads: everything in local and test; without the web overrides elsewhere. */
export function flagEnvironment(record: Environment, envName: WebEnvName): Environment {
  if (isLocalOrTest(envName)) return record;
  return Object.fromEntries(Object.entries(record).filter(([key]) => !isWebOverride(key)));
}

function logLine(line: string): void {
  console.warn(line);
}

type FlagProvider = Awaited<ReturnType<typeof configureFlags>>;

let configured: Promise<FlagProvider> | undefined;

function configure(log: FlagLog): Promise<FlagProvider> {
  configured ??= configureFlags(flagEnvironment(process.env, getEnv().CW_WEB_ENV), {
    serviceName: "web",
    log,
  });
  return configured;
}

/**
 * Whether the reader can answer, and through which provider: `env` or `unleash`, as
 * `CW_FLAGS_PROVIDER` chose; or why it could not be configured, in which case every web flag
 * reads as off. The flag console shows this above the values it evaluates.
 */
export type FlagProviderStatus = { ok: true; provider: string } | { ok: false; reason: string };

export async function flagProviderStatus(): Promise<FlagProviderStatus> {
  try {
    const provider = await configure(logLine);
    return { ok: true, provider: provider.metadata.name };
  } catch (error) {
    configured = undefined;
    return { ok: false, reason: error instanceof Error ? error.message : String(error) };
  }
}

/** Whether the web flag is on; off when the provider could not be configured. */
export async function isEnabled(name: FlagName, target: FlagTarget = {}): Promise<boolean> {
  try {
    await configure(logLine);
  } catch (error) {
    configured = undefined;
    logLine(
      JSON.stringify({
        level: "warn",
        event: "flag_configuration_failed",
        flag: name,
        error: error instanceof Error ? error.message : String(error),
      }),
    );
    return false;
  }
  return registryIsEnabled(
    name,
    target.tenantId === undefined ? {} : { tenantId: target.tenantId },
  );
}

/** Forgets the configured provider, so the next question reads the environment again (tests). */
export async function resetFlagReader(): Promise<void> {
  configured = undefined;
  await resetFlags();
}
