/**
 * Feature flags model: types and server query stub for the admin flags screen.
 */

import { FLAG_NAMES } from "@/shared/config/flags";
import type { FlagName } from "@/shared/config/flags";

export interface FlagView {
  name: FlagName;
  description: string;
  enabled: boolean;
  changedAt: string;
  changedBy: string;
}

export async function flags(): Promise<
  { ok: true; value: FlagView[] } | { ok: false; error: { kind: string; message: string } }
> {
  // TODO: read packages/flags/registry.json
  return { ok: true, value: [] };
}

export const FLAG_DESCRIPTIONS: Readonly<Record<FlagName, string>> = {
  "web.admin_rulebook_writes": "Allow the admin shell to write to the rulebook.",
  "web.analytics_enabled": "Record product analytics events.",
  "web.otel_enabled": "Emit OpenTelemetry traces and metrics.",
  "web.publish_actions": "Surface the publish action on the rulebook screen.",
  "web.qa_enabled": "Show the Q&A triage tools to reviewers.",
  "web.tenant_header_off": "Hide the tenant header on small screens.",
};

/** Every flag known to the registry, with its default of disabled. */
export function defaultFlags(): FlagView[] {
  return FLAG_NAMES.map((name) => ({
    name,
    description: FLAG_DESCRIPTIONS[name],
    enabled: false,
    changedAt: "—",
    changedBy: "—",
  }));
}
