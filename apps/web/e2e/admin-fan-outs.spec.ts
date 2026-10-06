import { randomUUID } from "node:crypto";
import {
  ADMIN,
  ANALYST,
  IS_CI,
  OWNER,
  REVIEWER,
  expect,
  seededTenantId,
  serviceUrl,
  test,
  waitForHydration,
} from "./fixtures";
import { latestVersion } from "./rulebook-helpers";

/**
 * The fan-out screens against the engine `make web-stack` starts. That stack runs no worker, so
 * the rulebook's drafts never fan out: the list is compared with the engine's (empty unless
 * something published to it), and a version's page shows a seeded draft with no run and no
 * rollback (a draft cannot be withdrawn, and no spec publishes one). The global hold is real on
 * the stack: an admin sets it with a reason and releases it, compared with the engine each time;
 * the specs here run one at a time because the hold is one switch, and a hold this spec left
 * (an interrupted run) is lifted first, so it runs again on the same stack. Pausing, resuming,
 * cancelling and the rollback's dialog are covered by the unit tests, since nothing here runs.
 */
const LIST = "/admin/fan-outs";
const HOLD_MARK = "Example e2e hold";

interface HoldBody {
  held: boolean;
  reason: string | null;
}

async function engine<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${serviceUrl("applicability-engine")}${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...init.headers },
  });
  expect(response.ok, `${path}: ${response.status}`).toBe(true);
  return (await response.json()) as T;
}

/** Lifts a hold an interrupted run of this spec left; anyone else's is left alone. */
async function liftOwnHold(): Promise<void> {
  const hold = await engine<HoldBody>("/v1/applicability-engine/fan-out-hold");
  if (hold.held && (hold.reason ?? "").startsWith(HOLD_MARK)) {
    await engine("/v1/applicability-engine/fan-out-hold", {
      method: "PUT",
      body: JSON.stringify({
        held: false,
        reason: `${HOLD_MARK}: lifting a hold an earlier run left`,
      }),
    });
  }
}

test.describe("fan-outs", () => {
  test("a tenant role gets a 404 for the list and a version's fan-out", async ({
    page,
    signIn,
  }) => {
    await signIn(OWNER);
    for (const path of [LIST, `${LIST}/${randomUUID()}`]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test("a malformed id is the not-found page", async ({ page, signIn, checkA11y }) => {
    await signIn(ADMIN);
    await page.goto(`${LIST}/not-a-version`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await checkA11y();
  });

  test.describe("against the stack", () => {
    test.describe.configure({ mode: "serial" });
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
    );

    test("an analyst reads the runs and the hold from the sidebar, with no control", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      await liftOwnHold();
      const runs = await engine<{ items: { rule_version_id: string }[] }>(
        "/v1/applicability-engine/fan-outs?limit=25",
      );
      const hold = await engine<HoldBody>("/v1/applicability-engine/fan-out-hold");
      await signIn(ANALYST);
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Fan-outs" }).click();
      await expect(page).toHaveURL(new RegExp(`${LIST}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Fan-outs" })).toBeVisible();
      if (runs.items.length === 0) {
        await expect(
          page.getByRole("heading", { level: 2, name: "No fan-out has run yet" }),
        ).toBeVisible();
      } else {
        await expect(page.locator("tr[data-fan-out]")).toHaveCount(runs.items.length);
      }
      const panel = page.locator("[data-slot='fan-out-hold']");
      await expect(panel).toHaveAttribute("data-held", String(hold.held));
      await expect(panel.getByRole("button")).toHaveCount(0);
      await expect(panel).toContainText("Only an admin sets or releases the hold.");
      await checkA11y();
    });

    test("an admin holds every fan-out with a reason, and releases it", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      await liftOwnHold();
      const reason = `${HOLD_MARK} ${new Date().toISOString()}: checking the controls`;
      await signIn(ADMIN);
      try {
        await page.goto(LIST);
        const panel = page.locator("[data-slot='fan-out-hold']");
        await expect(panel).toHaveAttribute("data-held", "false");
        await waitForHydration(page, "[data-slot='fan-out-hold'] button");
        await panel.getByRole("button", { name: "Hold every fan-out" }).click();
        const dialog = page.getByRole("dialog", { name: "Hold every fan-out?" });
        await dialog.getByRole("textbox").fill("Too short");
        await expect(dialog.getByRole("button", { name: "Hold every fan-out" })).toBeDisabled();
        await dialog.getByRole("textbox").fill(reason);
        await dialog.getByRole("button", { name: "Hold every fan-out" }).click();
        await expect(panel).toHaveAttribute("data-held", "true");
        const banner = panel.locator("[data-slot='hold-banner']");
        await expect(banner).toContainText("Every fan-out is on hold");
        await expect(banner).toContainText(`Why: ${reason}`);
        await expect(panel.locator("[data-slot='control-done']")).toHaveText(
          "The hold is set: no fan-out starts its next batch until it is released.",
        );
        const held = await engine<HoldBody>("/v1/applicability-engine/fan-out-hold");
        expect(held).toMatchObject({ held: true, reason });
        await checkA11y();

        await panel.getByRole("button", { name: "Release the hold" }).click();
        const release = page.getByRole("dialog", { name: "Release the hold?" });
        await release.getByRole("textbox").fill(`${HOLD_MARK}: the check is done`);
        await release.getByRole("button", { name: "Release the hold" }).click();
        await expect(panel).toHaveAttribute("data-held", "false");
        await expect(panel.locator("[data-slot='hold-off']")).toBeVisible();
        expect((await engine<HoldBody>("/v1/applicability-engine/fan-out-hold")).held).toBe(false);
        await checkA11y();
      } finally {
        await liftOwnHold();
      }
    });

    test("a version with no run shows the version and offers no rollback of a draft", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const draft = await latestVersion(0);
      await signIn(ADMIN);
      await page.goto(`${LIST}/${draft.rule_version_id}`);
      const name = `${draft.rule_key} v${draft.version}`;
      await expect(
        page.getByRole("heading", { level: 1, name: `Fan-out of ${name}` }),
      ).toBeVisible();
      await expect(
        page.getByRole("navigation", { name: "Breadcrumb" }).getByText(name),
      ).toBeVisible();
      await expect(
        page.getByRole("heading", { level: 2, name: "No fan-out for this version" }),
      ).toBeVisible();
      await expect(page.locator("[data-slot='no-run']")).toContainText("this one is Draft.");
      await expect(page.locator("[data-slot='rollback-not-published']")).toHaveText(
        "Only a published version can be rolled back. This one is Draft.",
      );
      await expect(page.getByRole("button", { name: "Roll back this version" })).toHaveCount(0);
      const facts = page.locator("[data-slot='version-facts']");
      await expect(facts.getByRole("link", { name })).toHaveAttribute(
        "href",
        `/admin/rulebook/versions/${draft.rule_version_id}`,
      );
      await expect(
        page.getByRole("link", { name: "Dry run this version in the impact explorer" }),
      ).toHaveAttribute("href", `/admin/impact?rule_version_id=${draft.rule_version_id}`);
      await checkA11y();
    });

    test("a reviewer reads a version's page with no control", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const draft = await latestVersion(0);
      await signIn(REVIEWER);
      await page.goto(`${LIST}/${draft.rule_version_id}`);
      await expect(page.getByRole("heading", { level: 1 })).toContainText("Fan-out of");
      await expect(page.locator("[data-slot='rollback-admin-only']")).toHaveText(
        "Only an admin rolls a version back.",
      );
      await expect(page.locator("[data-slot='hold-admin-only']")).toBeVisible();
      await expect(
        page.getByRole("button", { name: /Hold|Release|Roll back|Pause|Resume|Cancel/ }),
      ).toHaveCount(0);
      await expect(page.getByRole("link", { name: /Dry run this version/ })).toHaveCount(0);
      await checkA11y();
    });

    test("a version neither the engine nor the rulebook holds is the not-found page", async ({
      page,
      signIn,
    }) => {
      await signIn(ADMIN);
      await page.goto(`${LIST}/${randomUUID()}`);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    });
  });
});
