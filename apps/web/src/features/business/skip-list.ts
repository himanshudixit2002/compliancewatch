import "server-only";

import { cookies } from "next/headers";
import { getEnv } from "@/server/env";
import { parseSkipList, serialiseSkipList, skipCookieName, withSkip } from "./model/questions";

/**
 * The questions step's skip list in an httpOnly cookie, one per business: the checklist items
 * answered "Not sure" in this run, so the step moves past them (model/questions.ts says why).
 * The cookie holds node ids and attribute keys, nothing a person typed; it lives for a day and
 * only under /onboarding. Pages read it; only the server actions write it, since Next allows a
 * cookie to be set in a Server Function or Route Handler and never during a render.
 */
export const SKIP_COOKIE_MAX_AGE_SECONDS = 24 * 60 * 60;

const COOKIE_PATH = "/onboarding";

export async function readSkipList(businessId: string): Promise<Set<string>> {
  const store = await cookies();
  return parseSkipList(store.get(skipCookieName(businessId))?.value);
}

/** Adds the item (an unsure answer) or removes it (any other answer). Server actions only. */
export async function rememberSkip(businessId: string, item: string, skip: boolean): Promise<void> {
  const current = await readSkipList(businessId);
  if (current.has(item) === skip) return;
  await writeSkipList(businessId, withSkip(current, item, skip));
}

/** Forgets every skipped item, so the step asks the unsure questions again. Server actions only. */
export async function clearSkipList(businessId: string): Promise<void> {
  const store = await cookies();
  store.delete({ name: skipCookieName(businessId), path: COOKIE_PATH });
}

async function writeSkipList(businessId: string, items: ReadonlySet<string>): Promise<void> {
  const store = await cookies();
  store.set(skipCookieName(businessId), serialiseSkipList(items), {
    httpOnly: true,
    sameSite: "lax",
    secure: getEnv().CW_WEB_ENV !== "local",
    path: COOKIE_PATH,
    maxAge: SKIP_COOKIE_MAX_AGE_SECONDS,
  });
}
