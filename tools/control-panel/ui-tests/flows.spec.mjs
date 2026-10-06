// The core flows on whichever helper the suite runs against: the mock, set up for each flow, or
// panel_server.py --demo with its own fixed scenarios (a branch that is not main, another
// session at work, gate:lint failing, the product stopped).

import { baseUrl, confirmIfAsked, expect, setWorld, openApp, test, token } from "./helpers.mjs";

const SCENE = {
  docker: true,
  infra: true,
  services: 10,
  web: true,
  branch: "demo-branch",
  sessions: "agent",
};

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true }, world: SCENE });
});

test("a run streams its steps and output, and can be cancelled", async ({ page, request }) => {
  await setWorld(request, { speed: 0.1 });
  await openApp(page, "run");
  const card = page.locator("#action-start-everything");
  await card.getByRole("button", { name: "Start", exact: true }).click();
  // on a branch other than main, starting migrates the shared database: it asks first
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("not main");
  await dialog.locator(".dialog-footer .btn").last().click();
  await expect(card).toHaveAttribute("data-state", "running");
  await expect(card.locator(".run-headline")).toContainText(/Step \d of 7/);
  await expect(card.getByRole("progressbar")).toBeVisible();
  await card.getByRole("button", { name: "Show the live output" }).click();
  await expect(card.getByRole("log").locator(".ln").first()).toBeVisible();
  await card.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Cancel it" }).click();
  await expect(page.locator(".toast", { hasText: "Start everything: cancelled" })).toBeVisible({
    timeout: 20000,
  });
  await expect(card).toHaveAttribute("data-state", "cancelled");
});

test("a failing check says so plainly, with its lines one click away", async ({
  page,
  request,
}) => {
  await setWorld(request, {
    failNext: {
      action: "gate:lint",
      step: 0,
      lines: [
        "apps/web/src/app/admin/page.tsx",
        "  12:7  error  'unused' is assigned a value but never used",
        "make: *** [ts-lint] Error 1",
      ],
    },
  });
  await openApp(page, "checks");
  const card = page.locator("[id='action-gate:lint']");
  await card.getByRole("button", { name: "Check" }).click();
  await expect(card).toHaveAttribute("data-state", "failed", { timeout: 20000 });
  await expect(card.locator(".run-headline")).toContainText("it did not pass");
  await expect(card.locator(".run-fix")).toContainText("Fix that, then run the check again.");
  await expect(card.getByRole("button", { name: "Try again" })).toBeVisible();
  await card.getByRole("button", { name: "Show technical details" }).click();
  await expect(card.locator(".run-failure .code-block")).toContainText("error");
  await expect(page.locator(".toast.tone-danger")).toContainText("did not pass");
});

test("Stop everything asks first, naming what it reaches and who it would break", async ({
  page,
}) => {
  await openApp(page);
  await page.getByRole("button", { name: "Stop everything" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Stop everything?" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expect(dialog.locator(".banner.tone-danger").first()).toContainText("Claude's build agent");
  await expect(dialog).toContainText("These processes get a request to stop");
  await expect(dialog.locator(".pid-list li").first()).toContainText("pnpm --filter web dev");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
});

test("an action that cannot run says why and offers what makes it possible", async ({ page }) => {
  await openApp(page, "data");
  const card = page.locator("#action-product-seed");
  await expect(card.getByRole("button", { name: "Fill" })).toBeDisabled();
  await expect(card.locator(".ac-reason")).toContainText(/product/i);
  await expect(card.locator(".ac-fix")).toHaveText("Start the product");
});

test("the first launch shows the tour, and it can be skipped", async ({ page, request }) => {
  await request.put(`${baseUrl()}/api/prefs`, {
    headers: { "X-Panel-Token": token(), "Content-Type": "application/json" },
    data: { tour_done: false },
  });
  await openApp(page);
  const card = page.getByRole("dialog", { name: "Start and stop everything here" });
  await expect(card).toBeVisible();
  await expect(card).toContainText("1 of 5");
  await card.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("dialog", { name: "See what is running" })).toBeVisible();
  await page.getByRole("button", { name: "Skip the tour" }).click();
  await expect(page.locator(".tour-layer")).toHaveCount(0);
  const prefs = await request.get(`${baseUrl()}/api/prefs`, {
    headers: { "X-Panel-Token": token() },
  });
  expect(await prefs.json()).toMatchObject({ tour_done: true });
});

test("the window is in step with the helper it talks to", async ({ page }) => {
  await openApp(page);
  await expect(page.locator("#branch-chip")).toContainText("demo-branch");
  await expect(page.locator("#branch-chip")).toHaveAttribute("data-tone", "danger");
  await expect(page.locator(".pill[data-part='web']")).toHaveAttribute("data-state", "running");
});
