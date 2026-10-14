import "server-only";

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { headers } from "next/headers";
import { z } from "zod";
import { readPending, type PendingSignIn } from "@/server/auth/pending";
import { getEnv, type WebEnv } from "@/server/env";
import { requestHost } from "@/server/origin";
import { hrefFor, screenById } from "@/shared/config/screens";
import { isUuid } from "@/shared/lib/identifiers";

/**
 * What the sign-in pages read before they render: the seed's last tenant for the development
 * form, the pending sign-in a person carries between the steps, and the address of the email
 * link's callback on this deployment.
 */
export interface SeedState {
  tenantId: string;
  seededAt?: string;
}

const seedFileSchema = z.object({
  tenant_id: z.string().refine(isUuid, { error: "not a UUID" }),
  seeded_at: z.string().optional(),
});

// The file is written by the seed at run time, outside the app; the ignore comments keep the
// output tracing from pulling the whole project into the server bundle for this one path.
export function seedStatePath(env = getEnv()): string {
  return resolve(/* turbopackIgnore: true */ process.cwd(), env.CW_WEB_SEED_STATE_PATH);
}

/**
 * What the seed script recorded about the last tenant it filled (CW_WEB_SEED_STATE_PATH,
 * `var/seed/last.json` relative to apps/web by default), so the development sign-in can offer
 * that tenant instead of a blank one. Absent, unreadable or malformed means null: the form
 * simply does not offer the option.
 */
export async function seedState(): Promise<SeedState | null> {
  let text: string;
  try {
    text = await readFile(/* turbopackIgnore: true */ seedStatePath(), "utf8");
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

/** The pending sign-in of the request (cw_pending), or null. */
export function pendingSignIn(): Promise<PendingSignIn | null> {
  return readPending();
}

/**
 * Where the email link comes back to: the callback handler's route on this deployment's origin,
 * `CW_WEB_PUBLIC_URL` (required with the supabase provider: a request header must not decide
 * where a sign-in link is sent back to) or, for the fake adapter, which sends nothing, the host
 * the browser asked for (the forwarded host behind a trusted proxy) over https outside local.
 * The path to return to after signing in rides along as `next`, always present (empty when
 * there is none), so the provider's email template can append the hash with `&`.
 */
export async function callbackUrl(next?: string, env: WebEnv = getEnv()): Promise<string> {
  const origin = env.CW_WEB_PUBLIC_URL ?? (await requestOrigin(env));
  const url = new URL(hrefFor(screenById("system.auth-callback")), origin);
  url.searchParams.set("next", next ?? "");
  return url.toString();
}

/** The origin the browser asked for, from the request's headers (the fake adapter only). */
async function requestOrigin(env: WebEnv): Promise<string> {
  const incoming = await headers();
  const trust = env.CW_WEB_TRUST_FORWARDED_IP;
  const host = requestHost(incoming, { trustForwardedHost: trust }) ?? "localhost";
  const forwardedProto = trust ? incoming.get("x-forwarded-proto")?.split(",")[0]?.trim() : "";
  const proto = forwardedProto || (env.CW_WEB_ENV === "local" ? "http" : "https");
  return `${proto}://${host}`;
}
