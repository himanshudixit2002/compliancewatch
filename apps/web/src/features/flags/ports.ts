import type { FlagDefinition } from "@compliancewatch/flags";
import type { FlagName } from "@/shared/config/flags";
import type { FlagProviderView } from "./model/flags";

/**
 * What the flag console reads: the registry's entries (a file in the build, the same for every
 * request) and the web server's reader, which answers for the web app's own flags only.
 */
export interface FlagConsolePort {
  /** Every flag in packages/flags/registry.json, in registry order. */
  definitions(): readonly FlagDefinition[];
  provider(): Promise<FlagProviderView>;
  /** Whether a web flag is on for the tenant, as the reader answers. */
  isEnabled(name: FlagName, tenantId: string): Promise<boolean>;
}
