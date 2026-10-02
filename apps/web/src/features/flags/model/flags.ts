import { REGISTRY } from "@compliancewatch/flags";
import type { FlagOwner } from "@compliancewatch/flags";
import { FLAG_NAMES, envVarFor } from "@/shared/config/flags";
import type { FlagName } from "@/shared/config/flags";

/**
 * One web flag as the admin flags screen shows it: its entry in packages/flags/registry.json
 * (the one source of its description, owner, removal condition and expiry) and whether the
 * server's flag reader has it on for this request.
 */
export interface FlagView {
  name: FlagName;
  description: string;
  owner: FlagOwner;
  removal: string;
  /** The registry's expiry date, YYYY-MM-DD. */
  expires: string;
  /** The override variable honoured in local and test. */
  env: string;
  enabled: boolean;
}

export interface FlagSummary {
  total: number;
  enabled: number;
  expired: number;
}

/** Every web flag in registry order, with its state as the server's flag reader answered. */
export function flagViews(enabled: Readonly<Record<FlagName, boolean>>): FlagView[] {
  return FLAG_NAMES.map((name) => {
    const entry = REGISTRY.get(name);
    return {
      name,
      description: entry.description,
      owner: entry.owner,
      removal: entry.removal,
      expires: entry.expires,
      env: envVarFor(name),
      enabled: enabled[name],
    };
  });
}

/** True once the flag's expiry date has passed; `today` is a YYYY-MM-DD key. */
export function isExpired(flag: Pick<FlagView, "expires">, today: string): boolean {
  return flag.expires < today;
}

/** The counts for the summary row: flags, flags on, flags past their expiry date. */
export function flagSummary(flags: readonly FlagView[], today: string): FlagSummary {
  return {
    total: flags.length,
    enabled: flags.filter((flag) => flag.enabled).length,
    expired: flags.filter((flag) => isExpired(flag, today)).length,
  };
}
