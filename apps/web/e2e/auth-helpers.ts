import { randomInt } from "node:crypto";
import type { Page } from "@playwright/test";
import { expect } from "./fixtures";

/**
 * Helpers for the specs that take the real sign-in: a phone number nobody holds (+91 followed
 * by a zero, which no Indian mobile number starts with, then random digits), the phone and
 * code steps on the sign-in page, and the invite dialog on a team page.
 */
export function uniquePhone(): string {
  return `+910${String(randomInt(0, 1_000_000_000)).padStart(9, "0")}`;
}

export function uniqueEmail(prefix = "person"): string {
  return `${prefix}-${randomInt(0, 1_000_000_000).toString(36)}@example.test`;
}

/** Any six digits pass with the fake adapter; this one is as good as another. */
export const ANY_CODE = "123456";

/** The phone step and the code step; resolves once the page left the sign-in form. */
export async function signInByPhone(page: Page, phone: string, next?: string): Promise<void> {
  const target = new URL("/sign-in", "http://localhost");
  target.searchParams.set("method", "phone");
  if (next !== undefined) target.searchParams.set("next", next);
  await page.goto(`${target.pathname}${target.search}`);
  await page.getByLabel(/Mobile number/).fill(phone);
  await page.getByRole("button", { name: "Send code" }).click();
  await expect(page.getByLabel(/^Code/)).toBeVisible();
  await page.getByLabel(/^Code/).fill(ANY_CODE);
  await page.getByRole("button", { name: "Verify" }).click();
  await page.waitForURL((url) => url.pathname !== "/sign-in");
}

export interface Invitation {
  contact: string;
  name: string;
  roles: readonly string[];
}

/** Opens the invite dialog on the team page shown and sends the invitation. */
export async function inviteThroughDialog(page: Page, invitation: Invitation): Promise<void> {
  await page.getByRole("button", { name: "Invite" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel(/Mobile number or email address/).fill(invitation.contact);
  await dialog.getByLabel(/^Name/).fill(invitation.name);
  for (const role of invitation.roles) {
    await dialog.getByRole("checkbox", { name: role }).check();
  }
  await dialog.getByRole("button", { name: "Send invitation" }).click();
  await expect(dialog).toBeHidden();
}
