/**
 * The names of the web app's feature flags. Each flag is declared in the repository's flag
 * registry, packages/flags/registry.json, with every other rollout switch: its owner, its
 * default (always off), its removal condition and its expiry date, checked by `make flags-check`.
 * This file keeps the typed list the screen registry and the navigation name a flag by;
 * flags.test.ts holds the list and the registry's `web.*` entries to each other.
 *
 * A flag is read on the server only and never reaches the browser. Its override variable is the
 * registry entry's `env`, CW_WEB_FLAG_<NAME> (the name after `web.`, upper-cased), honoured only
 * when CW_WEB_ENV is local or test.
 */
export const FLAG_NAMES = [
  "web.admin_rulebook_writes",
  "web.analytics_enabled",
  "web.otel_enabled",
  "web.publish_actions",
  "web.qa_enabled",
  "web.tenant_header_off",
] as const;

export type FlagName = (typeof FLAG_NAMES)[number];

export function isFlagName(value: string): value is FlagName {
  return (FLAG_NAMES as readonly string[]).includes(value);
}

/** The environment variable that overrides a flag in local and test: web.qa_enabled -> CW_WEB_FLAG_QA_ENABLED. */
export function envVarFor(name: FlagName): string {
  return `CW_WEB_FLAG_${name.replace(/^web\./, "").toUpperCase()}`;
}
