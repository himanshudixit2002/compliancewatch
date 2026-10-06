import "server-only";

import { isEnabled } from "@/server/flags";
import type { FlagName } from "@/shared/config/flags";
import { SCREENS, type Screen } from "@/shared/config/screens";

/** The flags the business pages sit behind, read from the registry. */
export function businessPageFlags(screens: readonly Screen[] = SCREENS): FlagName[] {
  const flags = screens
    .filter((screen) => screen.kind === "page" && screen.route.startsWith("/b/[businessId]"))
    .flatMap((screen) => (screen.flag === undefined ? [] : [screen.flag]));
  return [...new Set(flags)];
}

/**
 * Which of those flags are on for the session's tenant, so a business page's tabs list a flagged
 * page (Ask) only where it opens. Read on the server, per request, like every flag.
 */
export async function businessFlags(
  viewer: { tenantId: string },
  screens: readonly Screen[] = SCREENS,
): Promise<ReadonlySet<FlagName>> {
  const flags = businessPageFlags(screens);
  const answers = await Promise.all(
    flags.map(
      async (flag) => [flag, await isEnabled(flag, { tenantId: viewer.tenantId })] as const,
    ),
  );
  return new Set(answers.filter(([, on]) => on).map(([flag]) => flag));
}
