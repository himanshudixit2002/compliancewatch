import type { FlagDefinition, FlagOwner } from "@compliancewatch/flags";
import { daysBetween } from "@/shared/lib/dates";

/**
 * The flag console's model: every entry of packages/flags/registry.json (the one source of a
 * flag's description, owner, default, removal condition and expiry) as a row, with the value the
 * web server's reader answers for the flags the web app reads. Other services read their flags
 * from their own variables or Unleash, which the web server cannot see, so their rows say who
 * reads them instead of guessing a value.
 */
export const WEB_SERVICE = "web";

/** A flag whose expiry date is this close is flagged on the console. */
export const EXPIRY_WARNING_DAYS = 30;

export type ExpiryState = "expired" | "soon" | "later";

export interface Expiry {
  state: ExpiryState;
  /** Whole days from today (IST) to the expiry date; negative once it has passed. */
  days: number;
}

/**
 * The value column: `on` or `off` as the web server's reader answered, `unknown` for a flag the
 * web app reads while the reader could not be configured, `elsewhere` for a flag only other
 * services read.
 */
export type FlagValue =
  | { kind: "on" }
  | { kind: "off" }
  | { kind: "unknown" }
  | { kind: "elsewhere"; services: readonly string[] };

export interface FlagRow {
  name: string;
  type: FlagDefinition["type"];
  /** A bool flag's default is off; a string flag's is one of its values. */
  defaultValue: boolean | string;
  /** A string flag's values; empty for a bool flag. */
  values: readonly string[];
  owner: FlagOwner;
  description: string;
  removal: string;
  /** YYYY-MM-DD. */
  expires: string;
  expiry: Expiry;
  targeting: FlagDefinition["targeting"];
  /** The variable the code reads for the switch, when it has one. */
  env: string | null;
  /** The variable holding a tenant allow-list, when the code reads one. */
  tenantsEnv: string | null;
  services: readonly string[];
  value: FlagValue;
}

export interface FlagSummary {
  total: number;
  /** Flags the web app reads. */
  web: number;
  /** Of those, the ones the web server has on. */
  webOn: number;
  expiringSoon: number;
  expired: number;
}

/** How far the expiry date is from today; `today` is an IST date key. */
export function expiryOf(expires: string, today: string): Expiry {
  const days = daysBetween(today, expires);
  if (days < 0) return { state: "expired", days };
  if (days <= EXPIRY_WARNING_DAYS) return { state: "soon", days };
  return { state: "later", days };
}

export function isReadByWeb(definition: Pick<FlagDefinition, "services">): boolean {
  return definition.services.includes(WEB_SERVICE);
}

/**
 * One row per registry entry, in registry order (sorted by name). `values` holds the reader's
 * answer for each web flag it evaluated; null when the reader could not be configured.
 */
export function flagRows(
  definitions: readonly FlagDefinition[],
  values: ReadonlyMap<string, boolean> | null,
  today: string,
): FlagRow[] {
  return definitions.map((definition) => {
    let value: FlagValue;
    if (!isReadByWeb(definition)) {
      value = { kind: "elsewhere", services: definition.services };
    } else {
      const evaluated = values?.get(definition.name);
      value = evaluated === undefined ? { kind: "unknown" } : { kind: evaluated ? "on" : "off" };
    }
    return {
      name: definition.name,
      type: definition.type,
      defaultValue: definition.default,
      values: definition.values ?? [],
      owner: definition.owner,
      description: definition.description,
      removal: definition.removal,
      expires: definition.expires,
      expiry: expiryOf(definition.expires, today),
      targeting: definition.targeting,
      env: definition.env ?? null,
      tenantsEnv: definition.tenants_env ?? null,
      services: definition.services,
      value,
    };
  });
}

/** The figures above the table. */
export function flagSummary(rows: readonly FlagRow[]): FlagSummary {
  const web = rows.filter((row) => row.value.kind !== "elsewhere");
  return {
    total: rows.length,
    web: web.length,
    webOn: web.filter((row) => row.value.kind === "on").length,
    expiringSoon: rows.filter((row) => row.expiry.state === "soon").length,
    expired: rows.filter((row) => row.expiry.state === "expired").length,
  };
}

/** Whether the web server's flag reader can answer, and through which provider. */
export type FlagProviderView = { ok: true; provider: string } | { ok: false; reason: string };

/** Everything the console page shows. */
export interface FlagConsoleView {
  provider: FlagProviderView;
  rows: FlagRow[];
  summary: FlagSummary;
  /** Today in IST, YYYY-MM-DD: what the expiry badges are measured from. */
  today: string;
}

export function flagConsoleView(
  definitions: readonly FlagDefinition[],
  provider: FlagProviderView,
  values: ReadonlyMap<string, boolean> | null,
  today: string,
): FlagConsoleView {
  const rows = flagRows(definitions, provider.ok ? values : null, today);
  return { provider, rows, summary: flagSummary(rows), today };
}
