import "server-only";

import { isFlagName } from "@/shared/config/flags";
import { todayKey } from "@/shared/lib/dates";
import { flagConsoleGateway } from "./gateway";
import { flagConsoleView, isReadByWeb, type FlagConsoleView } from "./model/flags";
import type { FlagConsolePort } from "./ports";

/**
 * The flag console's read: every registry entry, and for the flags the web app reads, what the
 * web server's reader answers for the session's tenant. When the reader cannot be configured the
 * values are not evaluated (they would all read as off), and the page says why instead.
 */
export interface FlagConsoleDeps {
  port?: FlagConsolePort;
  now?: Date;
}

export async function getFlagConsole(
  session: { tenantId: string },
  deps: FlagConsoleDeps = {},
): Promise<FlagConsoleView> {
  const port = deps.port ?? flagConsoleGateway();
  const definitions = port.definitions();
  const provider = await port.provider();
  let values: Map<string, boolean> | null = null;
  if (provider.ok) {
    const names = definitions
      .filter(isReadByWeb)
      .map((definition) => definition.name)
      .filter(isFlagName);
    const answers = await Promise.all(names.map((name) => port.isEnabled(name, session.tenantId)));
    values = new Map(names.map((name, index) => [name, answers[index] === true]));
  }
  return flagConsoleView(definitions, provider, values, todayKey(deps.now));
}
