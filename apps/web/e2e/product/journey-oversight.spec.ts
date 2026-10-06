import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  ADMIN,
  IS_CI,
  expect,
  signInThroughForm,
  test,
  waitForHydration,
  type Persona,
} from "../fixtures";

/**
 * The oversight journey on the local product (`make product`, `make product-seed`, then the
 * fanout step of `make product-check`, which publishes the seed calendar's annual return behind
 * the global hold and lets it fan out). An admin finds that fan-out completed, opens it, and sets
 * and releases the global hold with a reason; runs a dry run of the annual return over the
 * synthetic CA firm and reads the engine's counts; and the CA firm's admin opens the change's
 * affected clients and sends the change card, then sends the same request again, which the
 * notification service answers with its first answer.
 *
 * Nothing here withdraws anything: the shared dev database keeps its published seed rules, and CI
 * proves the rollback in `make product-check --destructive` before this runs. On CI that check has
 * withdrawn the annual return, so its fan-out stays completed and its obligations are closed: the
 * change card then finds the client not affected, which the spec expects from the version's
 * status. The card goes to a synthetic client contact made for the run on a mailbox that cannot
 * exist (as `cw-product check` makes its own) and removed afterwards, so the spec runs again.
 */
const PRODUCT = process.env.CW_E2E_PRODUCT_URL?.trim().replace(/\/+$/, "") || null;

const ANNUAL_RULE = "gstr9_annual";

/** The synthetic CA firm `make product-seed` makes (tools/demo cw_demo.product.tenants). */
const CA_FIRM_TENANT = "00000000-0000-4000-8000-0000000d0002";

const HOLD_MARK = "Example web journey hold";
const CONTACT_DOMAIN = "demo-ca-associates.invalid";

interface RunBody {
  rule_version_id: string;
  rule_key: string;
  status: string;
  businesses_total: number;
  evaluated: number;
}

interface HoldBody {
  held: boolean;
  reason: string | null;
}

interface DryRunBody {
  businesses_total: number;
  evaluated: number;
  counts: { applies: number; not_applicable: number; unsure: number };
  samples: unknown[];
}

function seeded(): boolean {
  const configured = process.env.CW_WEB_SEED_STATE_PATH?.trim();
  const path = resolve(__dirname, "..", "..", configured || "../../var/seed/last.json");
  try {
    const state = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
    return typeof state.tenant_id === "string";
  } catch {
    return false;
  }
}

async function onProduct<T>(
  path: string,
  init: RequestInit & { tenant?: string } = {},
): Promise<T> {
  const { tenant, ...rest } = init;
  const response = await fetch(`${PRODUCT}${path}`, {
    ...rest,
    headers: {
      "content-type": "application/json",
      ...(tenant === undefined ? {} : { "x-tenant-id": tenant }),
      ...rest.headers,
    },
  });
  expect(response.ok, `${path}: ${response.status} ${await response.clone().text()}`).toBe(true);
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

/** The annual return's fan-out, which the fanout step of the product check leaves completed. */
async function annualRun(): Promise<RunBody> {
  const page = await onProduct<{ items: RunBody[] }>("/v1/applicability-engine/fan-outs?limit=200");
  const run = page.items.find((item) => item.rule_key === ANNUAL_RULE);
  expect(run, "make product-check's fanout step publishes the annual return").toBeDefined();
  return run as RunBody;
}

/** Releases a hold an interrupted run of this spec left; anyone else's makes the spec fail. */
async function liftOwnHold(): Promise<void> {
  const hold = await onProduct<HoldBody>("/v1/applicability-engine/fan-out-hold");
  if (!hold.held) return;
  expect(
    (hold.reason ?? "").startsWith(HOLD_MARK),
    `the fan-out hold is set by someone else (${hold.reason ?? "no reason"}); leaving it alone`,
  ).toBe(true);
  await onProduct("/v1/applicability-engine/fan-out-hold", {
    method: "PUT",
    body: JSON.stringify({
      held: false,
      reason: `${HOLD_MARK}: lifting a hold an earlier run left`,
    }),
  });
}

test.describe("the oversight journey", () => {
  test.skip(
    !IS_CI && (PRODUCT === null || !seeded()),
    "needs make product WEB=0, make product-seed, make product-check and CW_E2E_PRODUCT_URL",
  );

  test("an admin finds the annual return's completed fan-out and holds and releases every fan-out", async ({
    page,
    checkA11y,
  }) => {
    const run = await annualRun();
    expect(run.status).toBe("completed");
    await liftOwnHold();
    await signInThroughForm(page, ADMIN, "/admin");
    try {
      await page.locator("aside").getByRole("link", { name: "Fan-outs" }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Fan-outs" })).toBeVisible();
      let row = page.locator(`tr[data-fan-out='${run.rule_version_id}']`);
      for (let pages = 0; pages < 5 && (await row.count()) === 0; pages += 1) {
        await page.getByRole("link", { name: "Older fan-outs" }).click();
        row = page.locator(`tr[data-fan-out='${run.rule_version_id}']`);
      }
      await expect(row).toHaveAttribute("data-status", "completed");
      await expect(row).toContainText("Completed");
      await checkA11y();
      await row.getByRole("link").first().click();
      await expect(page).toHaveURL(new RegExp(`/admin/fan-outs/${run.rule_version_id}$`));
      await expect(page.getByRole("heading", { level: 1 })).toContainText(
        `Fan-out of ${ANNUAL_RULE} v`,
      );
      const facts = page.locator("[data-slot='run']");
      await expect(facts).toHaveAttribute("data-status", "completed");
      await expect(facts.getByRole("progressbar")).toHaveAttribute(
        "aria-valuetext",
        `${run.evaluated.toLocaleString("en-IN")} of ${run.businesses_total.toLocaleString("en-IN")} decided`,
      );
      await expect(page.getByText(/This run has finished/)).toBeVisible();
      await checkA11y();

      const reason = `${HOLD_MARK} ${new Date().toISOString()}: checking the oversight screens (synthetic)`;
      const panel = page.locator("[data-slot='fan-out-hold']");
      await waitForHydration(page, "[data-slot='fan-out-hold'] button");
      await panel.getByRole("button", { name: "Hold every fan-out" }).click();
      const dialog = page.getByRole("dialog", { name: "Hold every fan-out?" });
      await dialog.getByRole("textbox").fill(reason);
      await dialog.getByRole("button", { name: "Hold every fan-out" }).click();
      await expect(panel).toHaveAttribute("data-held", "true");
      await expect(panel.locator("[data-slot='hold-reason']")).toHaveText(`Why: ${reason}`);
      expect(await onProduct<HoldBody>("/v1/applicability-engine/fan-out-hold")).toMatchObject({
        held: true,
        reason,
      });
      await checkA11y();
      await panel.getByRole("button", { name: "Release the hold" }).click();
      const release = page.getByRole("dialog", { name: "Release the hold?" });
      await release.getByRole("textbox").fill(`${HOLD_MARK}: the check is done (synthetic)`);
      await release.getByRole("button", { name: "Release the hold" }).click();
      await expect(panel).toHaveAttribute("data-held", "false");
      expect((await onProduct<HoldBody>("/v1/applicability-engine/fan-out-hold")).held).toBe(false);
    } finally {
      await liftOwnHold();
    }
  });

  test("an admin's dry run of the annual return over the CA firm gives the engine's counts", async ({
    page,
    checkA11y,
  }) => {
    const run = await annualRun();
    const body = {
      rule_version_id: run.rule_version_id,
      scope: { tenant_id: CA_FIRM_TENANT, sample_size: 5 },
    };
    const expected = await onProduct<DryRunBody>("/v1/applicability-engine/dry-runs", {
      method: "POST",
      body: JSON.stringify(body),
    });
    expect(
      expected.businesses_total,
      "the CA firm's registrations are in the directory",
    ).toBeGreaterThan(0);
    await signInThroughForm(page, ADMIN, `/admin/impact?rule_version_id=${run.rule_version_id}`);
    await expect(page.getByRole("heading", { level: 1, name: "Impact explorer" })).toBeVisible();
    await waitForHydration(page, "[data-slot='dry-run-form'] input");
    const form = page.getByRole("form", { name: "Run a dry run" });
    await expect(form.getByLabel(/^Rule version id/)).toHaveValue(run.rule_version_id);
    await form.getByLabel(/^Tenant id/).fill(CA_FIRM_TENANT);
    await form.getByLabel(/^Sample decisions/).fill("5");
    await form.getByRole("button", { name: "Run the dry run" }).click();
    const report = page.locator("[data-slot='dry-run-report']");
    await expect(report).toContainText(`The businesses of tenant ${CA_FIRM_TENANT}`);
    await expect(report).toContainText(
      `${expected.businesses_total} in scope, ${expected.evaluated} decided`,
    );
    for (const [key, value] of Object.entries(expected.counts)) {
      await expect(page.locator(`[data-count='${key}'] dd`)).toHaveText(String(value));
    }
    await expect(page.locator("[data-slot='dry-run-samples'] tbody tr")).toHaveCount(
      expected.samples.length,
    );
    await checkA11y();
  });

  test("the CA firm's admin sends the annual return's change card, and the same request again shows the same outcome", async ({
    page,
    checkA11y,
  }) => {
    const run = await annualRun();
    const impact = await onProduct<{ items: { businesses: { business_id: string }[] }[] }>(
      `/v1/changes/${run.rule_version_id}/impact?result=applies&limit=200`,
      { tenant: CA_FIRM_TENANT },
    );
    const affected = impact.items.flatMap((client) => client.businesses.map((b) => b.business_id));
    expect(affected.length, "the annual return applies to a client of the CA firm").toBeGreaterThan(
      0,
    );
    const version = await onProduct<{ status: string }>(
      `/v1/rulebook/rule-versions/${run.rule_version_id}`,
    );
    // Published: the contact gets the card. Withdrawn (CI's rollback step ran): nothing is open.
    const expectedOutcome = version.status === "published" ? "queued" : "not_affected";

    const contact = randomUUID();
    const address = `web-journey-${contact.slice(0, 8)}@${CONTACT_DOMAIN}`;
    await onProduct(`/v1/notification/recipients/${contact}`, {
      method: "PUT",
      tenant: CA_FIRM_TENANT,
      body: JSON.stringify({
        role: "owner",
        language: "en",
        digest_mode: "off",
        addresses: [{ channel: "email", address }],
        businesses: affected.map((business_id) => ({ business_id, label: "" })),
      }),
    });
    await onProduct(`/v1/notification/preferences/email/${address}`, {
      method: "PUT",
      body: JSON.stringify({
        opted_in: true,
        source: "api",
        language: "en",
        quiet_hours_start: "00:00",
        quiet_hours_end: "00:00",
      }),
    });
    try {
      const caAdmin: Persona = {
        key: "product-ca-admin",
        tenantKind: "ca_firm",
        roles: ["ca_admin"],
        displayName: "Example product CA admin",
        tenantId: CA_FIRM_TENANT,
      };
      const path = `/changes/${run.rule_version_id}/impact`;
      await signInThroughForm(page, caAdmin, path);
      await expect(page.getByRole("heading", { level: 1, name: "Affected clients" })).toBeVisible();
      for (const business of affected) {
        await expect(page.locator(`tr[data-business='${business}']`)).toHaveAttribute(
          "data-result",
          "applies",
        );
      }
      await checkA11y();

      const send = page.getByRole("button", { name: /^Send the change card to/ });
      await waitForHydration(page, "[data-slot='bulk-panel'] button");
      await send.click();
      await page
        .getByRole("dialog", { name: "Send the change card?" })
        .getByRole("button", { name: "Send the change card" })
        .click();
      const outcome = page.locator("[data-slot='bulk-outcome']");
      await expect(outcome.locator("[data-slot='bulk-done']")).toHaveText(/^Sent\. /);
      for (const business of affected) {
        await expect(outcome.locator(`tr[data-business='${business}']`)).toHaveAttribute(
          "data-outcome",
          expectedOutcome,
        );
      }
      const first = await outcome.locator("[data-slot='bulk-done']").textContent();
      await checkA11y();

      await send.click();
      await page
        .getByRole("dialog", { name: "Send the change card?" })
        .getByRole("button", { name: "Send the change card" })
        .click();
      await expect(outcome).toHaveAttribute("data-replayed", "true");
      await expect(outcome.locator("[data-slot='bulk-done']")).toHaveText(
        `This request had already been sent, so nothing was sent twice. ${(first ?? "").replace(/^Sent\. /, "")}`,
      );
      for (const business of affected) {
        await expect(outcome.locator(`tr[data-business='${business}']`)).toHaveAttribute(
          "data-outcome",
          expectedOutcome,
        );
      }
      // One card per business for the contact, however often the same request was sent.
      for (const business of affected) {
        const notifications = await onProduct<{
          items: { occasion: string; recipient_id: string | null }[];
        }>(`/v1/notification/notifications?business_id=${business}&limit=200`, {
          tenant: CA_FIRM_TENANT,
        });
        const cards = notifications.items.filter(
          (item) => item.occasion === "change_card" && item.recipient_id === contact,
        );
        expect(cards).toHaveLength(expectedOutcome === "queued" ? 1 : 0);
      }
    } finally {
      await onProduct(`/v1/notification/recipients/${contact}`, {
        method: "DELETE",
        tenant: CA_FIRM_TENANT,
      });
    }
  });
});
