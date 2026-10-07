// Click through the web app: the browser tests on a separate, temporary test copy that stops at
// the end, after a cancel too, never on the person's own services; and make web-e2e on its own,
// which is never run here and leads to it.

import { expect, isMock, openApp, setWorld, test } from "./helpers.mjs";

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true } });
});

test("Click through the web app says it runs on a test copy and never touches your data", async ({
  page,
}) => {
  await openApp(page, "checks");
  const card = page.locator("[id='action-gate:web-e2e']");
  await expect(card).toHaveAttribute("data-safety", "safe");
  await expect(card.locator(".ac-summary")).toContainText(
    "on a separate, temporary copy of the services",
  );
  await expect(card.locator(".ac-duration")).toContainText("10 to 15 minutes");
  await card.getByRole("button", { name: "What happens" }).click();
  const what = card.locator(".ac-what-list");
  await expect(what).toContainText("Stops the copy at the end");
  await expect(what).toContainText("Your own data and running app are never touched");
  await expect(what).toContainText("the web app you have open keeps running while it builds");
  await card.getByRole("button", { name: "Show technical details" }).click();
  await expect(card.locator(".code-block")).toContainText(
    "make web-e2e STORE=memory WEB_STACK_DIR=var/web-stack-check SERVICE_PORT_BASE=9400 WEB_PORT=3410",
  );
});

test("a cancel stops the browser tests, and the test copy still stops", async ({
  page,
  request,
}) => {
  test.skip(isMock(), "the mock plays no clean-up step");
  await setWorld(request, {
    speed: 0.25,
    world: { docker: true, infra: true, services: 10, web: true },
  });
  await openApp(page, "checks");
  const card = page.locator("[id='action-gate:web-e2e']");
  await card.getByRole("button", { name: "Check" }).click(); // safe: no question first
  await expect(card).toHaveAttribute("data-state", "running");
  await expect(card.locator(".run-headline")).toContainText(
    "Step 2 of 6: Start a separate test copy of the services",
    { timeout: 15000 },
  );
  // your own services and web app go on running: their lights do not turn to "starting"
  await expect(page.locator(".pill[data-part='services']")).toHaveAttribute(
    "data-state",
    "running",
  );
  await expect(page.locator(".pill[data-part='web']")).toHaveAttribute("data-state", "running");
  await card.getByRole("button", { name: "Cancel" }).click();
  const confirm = page.getByRole("dialog", { name: 'Cancel "Click through the web app"?' });
  await expect(confirm).toContainText(
    "except “Stop the test copy”, which always runs last so that nothing is left running",
  );
  await confirm.getByRole("button", { name: "Cancel it" }).click();
  const toast = page.locator(".toast", { hasText: "Click through the web app: cancelled" });
  await expect(toast).toBeVisible({ timeout: 20000 });
  await expect(toast).toContainText("then “Stop the test copy” ran, so nothing is left running");
  await expect(card).toHaveAttribute("data-state", "cancelled");

  await page.locator("#activity-btn").click();
  const sheet = page.getByRole("dialog", { name: "Activity" });
  const row = sheet.locator(".activity-row", { hasText: "Click through the web app" });
  if ((await row.getAttribute("aria-expanded")) !== "true") await row.click();
  const steps = sheet.locator(".run-step");
  await expect(steps).toHaveCount(6);
  await expect(steps.nth(4)).toHaveAttribute("data-state", "cancelled");
  await expect(steps.last()).toHaveAttribute("data-state", "ok");
  await expect(steps.last()).toContainText("Stop the test copy");
  await page.keyboard.press("Escape");
});

test("make web-e2e on its own is never run, and leads to Click through the web app", async ({
  page,
}) => {
  await openApp(page, "commands");
  await page.getByRole("searchbox", { name: "Search every action" }).fill("web-e2e");
  const card = page.locator("[id='action-make:web-e2e']");
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-safety", "refused");
  await expect(card.getByRole("button", { name: "Run" })).toBeDisabled();
  await expect(card.locator(".ac-reason")).toContainText(
    "runs the browser tests against your own services",
  );
  await card.getByRole("button", { name: "Go to “Click through the web app”" }).click();
  await expect(page.locator("[id='action-gate:web-e2e']")).toBeInViewport();
  await expect(page.locator("[id='action-gate:web-e2e'] [data-role='run']")).toBeFocused();
});

test("with no browser for the tests it offers the download, which asks first", async ({
  page,
  request,
}) => {
  test.skip(isMock(), "the mock does not read a failure's words");
  await setWorld(request, {
    failNext: {
      action: "gate:web-e2e",
      step: 0,
      lines: [
        "error: there is no browser for the tests: Playwright's own Chromium is not downloaded here and Google Chrome is not installed. Download the test browser (make web-e2e-install, about 150 MB) or install Google Chrome, then try again",
      ],
    },
  });
  await openApp(page, "checks");
  const card = page.locator("[id='action-gate:web-e2e']");
  await card.getByRole("button", { name: "Check" }).click();
  await expect(card).toHaveAttribute("data-state", "failed", { timeout: 20000 });
  await expect(card.locator(".run-headline")).toContainText(
    "There is no browser for the browser tests",
  );
  await expect(card.locator(".run-fix")).toContainText("about 150 MB; it asks first");
  await card.getByRole("button", { name: "Download the test browser" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Downloads about 150 MB from the internet.");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
});
