import "server-only";

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { z } from "zod";
import { getEnv } from "@/server/env";
import { isUuid } from "@/shared/lib/identifiers";

/**
 * What the seed script recorded about the last tenant it filled (CW_WEB_SEED_STATE_PATH,
 * `var/seed/last.json` relative to apps/web by default), so the development sign-in can offer
 * that tenant instead of a blank one. Absent, unreadable or malformed means null: the form
 * simply does not offer the option.
 */
export interface SeedState {
  tenantId: string;
  seededAt?: string;
}

const seedFileSchema = z.object({
  tenant_id: z.string().refine(isUuid, { error: "not a UUID" }),
  seeded_at: z.string().optional(),
});

export function seedStatePath(env = getEnv()): string {
  return resolve(process.cwd(), env.CW_WEB_SEED_STATE_PATH);
}

export async function seedState(): Promise<SeedState | null> {
  let text: string;
  try {
    text = await readFile(seedStatePath(), "utf8");
  } catch {
    return null;
  }
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return null;
  }
  const parsed = seedFileSchema.safeParse(raw);
  if (!parsed.success) return null;
  const state: SeedState = { tenantId: parsed.data.tenant_id };
  if (parsed.data.seeded_at !== undefined) state.seededAt = parsed.data.seeded_at;
  return state;
}
