import "server-only";

import { REGISTRY } from "@compliancewatch/flags";
import { flagProviderStatus, isEnabled } from "@/server/flags";
import type { FlagConsolePort } from "./ports";

/**
 * The console's adapter: the registry module of `@compliancewatch/flags` (registry.json, built
 * into the app) and the web server's reader in server/flags.ts. Nothing here calls a service, and
 * nothing changes a flag: a flag moves through its variable or Unleash, never through the web.
 */
export function flagConsoleGateway(): FlagConsolePort {
  return {
    definitions: () => REGISTRY.flags,
    provider: () => flagProviderStatus(),
    isEnabled: (name, tenantId) => isEnabled(name, { tenantId }),
  };
}
