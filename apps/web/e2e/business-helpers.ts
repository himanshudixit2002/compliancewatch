import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { expect, serviceUrl, signInThroughForm, type Persona } from "./fixtures";

/**
 * Helpers for the owner and CA specs that need a business of their own. Each test signs in to a
 * new tenant (a fresh tenant id in the fake sign-in form), so the businesses it creates never
 * show up in another test's list and the seeded tenant keeps its one demo business.
 */
export function newTenantPersona(
  tenantKind: Persona["tenantKind"] = "business",
  roles: Persona["roles"] = ["owner"],
): Persona {
  const suffix = randomUUID().slice(0, 8);
  return {
    key: `tenant-${suffix}`,
    tenantKind,
    roles,
    displayName: `Example user ${suffix}`,
    tenantId: randomUUID(),
  };
}

export const REQUIRED_CONSENTS = [
  "I accept the terms of service.",
  "I have read the privacy notice.",
  /^Use the business identifiers and the profile answers I give/,
] as const;

/** Signs the persona in and records the three required consents through the consent step. */
export async function signInWithConsents(page: Page, persona: Persona): Promise<void> {
  await signInThroughForm(page, persona, "/onboarding");
  await expect(page.getByRole("heading", { level: 1, name: "Get started" })).toBeVisible();
  for (const name of REQUIRED_CONSENTS) await page.getByRole("checkbox", { name }).check();
  await page.getByRole("button", { name: "Agree and continue" }).click();
  await expect(page).toHaveURL(/\/onboarding\/business$/);
}

export interface CreatedBusiness {
  id: string;
  name: string;
  registrations: { id: string; key: string; name: string }[];
}

/**
 * Creates a business on the profile service directly (the business API, as the web server
 * calls it), for a spec about the pages that show one rather than the step that creates it.
 */
export async function createBusinessOnService(
  tenantId: string,
  body: { name: string; gstin?: string; pan?: string },
): Promise<CreatedBusiness> {
  const response = await fetch(`${serviceUrl("profile")}/v1/businesses`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-tenant-id": tenantId,
      "Idempotency-Key": randomUUID(),
    },
    body: JSON.stringify(body),
  });
  expect(response.status, await response.clone().text()).toBe(201);
  const created = (await response.json()) as { business: CreatedBusiness };
  return created.business;
}

/** GET /v1/businesses/{id} as the tenant, for a spec that reads back what a page stored. */
export async function readBusinessOnService(
  tenantId: string,
  businessId: string,
): Promise<Record<string, unknown>> {
  const response = await fetch(`${serviceUrl("profile")}/v1/businesses/${businessId}`, {
    headers: { "x-tenant-id": tenantId },
  });
  expect(response.status).toBe(200);
  return (await response.json()) as Record<string, unknown>;
}

/** GET /v1/profile/nodes/{id}/review-tasks as the tenant. */
export async function reviewTasksOnService(
  tenantId: string,
  nodeId: string,
): Promise<{ attribute_key: string; reason: string; open: boolean }[]> {
  const response = await fetch(`${serviceUrl("profile")}/v1/profile/nodes/${nodeId}/review-tasks`, {
    headers: { "x-tenant-id": tenantId },
  });
  expect(response.status).toBe(200);
  return (await response.json()) as { attribute_key: string; reason: string; open: boolean }[];
}

/** The seeded demo business's id (var/seed/last.json), or null when the seed has not run here. */
export function seededBusinessId(): string | null {
  const configured = process.env.CW_WEB_SEED_STATE_PATH?.trim();
  const path = resolve(__dirname, "..", configured || "../../var/seed/last.json");
  try {
    const state: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (typeof state === "object" && state !== null && "entity_node_id" in state) {
      return typeof state.entity_node_id === "string" ? state.entity_node_id : null;
    }
  } catch {
    // Absent or unreadable: the seed has not run on this machine.
  }
  return null;
}

/** A PAN of the right shape for the n-th synthetic business of a spec. */
export function examplePan(n: number): string {
  return `AAAPE${String(n).padStart(4, "0")}Z`;
}
