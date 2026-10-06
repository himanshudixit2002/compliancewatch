// Confirms name what stops or changes, warn about the branch and other sessions, ask for a
// backup before a reset, and send nothing when cancelled.

import { expect, isMock, openApp, setWorld, test } from "./helpers.mjs";

const RUNNING = { docker: true, infra: true, services: 10, web: true };

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true }, world: RUNNING });
});

test("Stop everything names what stops, and Cancel sends nothing", async ({ page }) => {
  const posts = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/run")) posts.push(r.url());
  });
  await openApp(page);
  await page.getByRole("button", { name: "Stop everything" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Stop everything?" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Stops the web app and the ten services.");
  await expect(dialog).toContainText("Shuts Docker (Colima) down.");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await expect(dialog.locator(".banner")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  expect(posts).toEqual([]);
});

test("a confirm warns when the checkout is not on main", async ({ page, request }) => {
  await setWorld(request, { world: { ...RUNNING, branch: "pipeline-ops" } });
  await openApp(page);
  await expect(page.locator("#branch-chip")).toHaveAttribute("data-tone", "warning");
  await expect(page.locator("#branch-chip")).toContainText("pipeline-ops");
  await page.evaluate(() => (window.location.hash = "#/data"));
  await page.locator("#action-migrate").getByRole("button", { name: "Run" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.locator(".banner").first()).toContainText("on pipeline-ops, not main");
});

test("Stop everything's preview names the web app's processes and other sessions", async ({
  page,
  request,
}) => {
  await setWorld(request, { world: { ...RUNNING, sessions: "agent" } });
  await openApp(page);
  await expect(page.locator("#branch-chip")).toHaveAttribute("data-tone", "danger");
  await page.getByRole("button", { name: "Stop everything" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Stop everything?" });
  await expect(dialog).toContainText("These processes get a request to stop");
  await expect(dialog.locator(".pid-list li").first()).toContainText(/\d+\s*pnpm --filter web dev/);
  const warning = dialog.locator(".banner.tone-danger");
  await expect(warning).toContainText("Claude's build agent is running make check");
  await expect(warning).toContainText("Stopping Docker or replacing its data will break them.");
  const sent = page.waitForRequest((r) => r.url().includes("/api/actions/stop-everything/run"));
  await dialog.getByRole("button", { name: "Stop everything" }).click();
  const body = (await sent).postDataJSON();
  expect(body.params).toEqual({});
  expect(body.confirm_token).toMatch(/^c-/);
  await expect(page.locator(".hero")).toHaveAttribute("data-state", /stopping|stopped/);
});

test("stopping the databases names the session it would break", async ({ page, request }) => {
  await setWorld(request, { world: { ...RUNNING, sessions: "agent" } });
  await openApp(page, "run");
  await page.locator("#action-databases-stop").getByRole("button", { name: "Stop" }).click();
  const warning = page.getByRole("dialog").locator(".banner.tone-danger");
  await expect(warning).toContainText("Other sessions are using Docker's databases and queues");
  await expect(warning).toContainText("make check (pid 61000, 3m 12s)");
});

test("a data change asks first, even on main with no other session", async ({ page }) => {
  await openApp(page, "data");
  await page.locator("#action-load-demo-data").getByRole("button", { name: "Load" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(page.locator("#action-load-demo-data")).not.toHaveAttribute("data-state", "running");
  const sent = page.waitForRequest((r) => r.url().includes("/api/actions/load-demo-data/run"));
  await dialog.locator(".dialog-footer .btn").last().click();
  expect((await sent).postDataJSON().confirm_token).toMatch(/^c-/);
  await expect(page.locator("#action-load-demo-data")).toHaveAttribute("data-state", "running");
});

test("an action that calls a model asks first, and says the model may be paid", async ({
  page,
}) => {
  test.skip(isMock(), "the mock calls no model");
  await openApp(page, "pipeline");
  const card = page.locator("#action-extract-backlog");
  await card.getByRole("button", { name: "Extract" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("This may call a paid model");
  await expect(dialog).toContainText("CW_LLM_PROVIDER");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(card).not.toHaveAttribute("data-state", "running");
});

test("a database change asks first on another branch", async ({ page, request }) => {
  await setWorld(request, { world: { ...RUNNING, branch: "pipeline-ops" } });
  await openApp(page, "data");
  await page.locator("#action-migrate").getByRole("button", { name: "Run" }).click();
  await expect(page.getByRole("dialog")).toContainText("shared development database");
});

test("Reset asks for a backup and an explicit yes", async ({ page }) => {
  await openApp(page, "data");
  await page.locator("#action-reset").getByRole("button", { name: "Reset" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("All local data is deleted");
  const backup = dialog.getByRole("checkbox", { name: "Back up first" });
  await expect(backup).toBeChecked();
  const yes = dialog.getByRole("button", { name: "Reset" });
  await expect(yes).toBeDisabled();
  await dialog
    .getByRole("checkbox", { name: "I understand that this deletes local data." })
    .check();
  await expect(yes).toBeEnabled();
  const request = page.waitForRequest((r) => r.url().includes("/api/actions/reset/run"));
  await yes.click();
  const body = (await request).postDataJSON();
  expect(body.params).toEqual({ backup_first: true });
  expect(body.confirm_token).toMatch(/^c-/);
  await expect(page.locator("#action-reset .run-panel")).toBeVisible();
});

test("changing an option previews again, so the run carries a matching token", async ({ page }) => {
  await openApp(page, "data");
  await page.locator("#action-reset").getByRole("button", { name: "Reset" }).click();
  const dialog = page.getByRole("dialog");
  const previews = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/actions/reset/preview")) previews.push(r.postDataJSON());
  });
  await dialog.getByRole("checkbox", { name: "Back up first" }).uncheck();
  await expect.poll(() => previews.length).toBe(1);
  expect(previews[0]).toEqual({ params: { backup_first: false } });
  await dialog
    .getByRole("checkbox", { name: "I understand that this deletes local data." })
    .check();
  const sent = page.waitForRequest((r) => r.url().includes("/api/actions/reset/run"));
  await dialog.getByRole("button", { name: "Reset" }).click();
  expect((await sent).postDataJSON().params).toEqual({ backup_first: false });
  await expect(page.locator("#action-reset .run-panel")).toBeVisible();
  await expect(page.locator("#action-reset .run-headline")).toContainText(
    "Step 1 of 7: Stop the UI-only stack",
  );
});

test("a question left open too long is asked again", async ({ page, request }) => {
  await openApp(page);
  await page.getByRole("button", { name: "Stop everything" }).first().click();
  const dialog = page.getByRole("dialog", { name: "Stop everything?" });
  await expect(dialog).toBeVisible();
  await setWorld(request, { expireTokens: true });
  await dialog.getByRole("button", { name: "Stop everything" }).click();
  await expect(page.locator(".toast", { hasText: "That question had expired" })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Stop everything?" })).toBeVisible();
  await page
    .getByRole("dialog", { name: "Stop everything?" })
    .getByRole("button", { name: "Cancel" })
    .click();
});

test("stopping a process shows every pid it reaches first", async ({ page, request }) => {
  await setWorld(request, { world: { ...RUNNING, sessions: "terminal" } });
  await openApp(page, "processes");
  // the helper behind this window has no Stop: closing the window stops it
  await expect(page.locator("tr", { hasText: "panel_server.py" })).toContainText(
    "Close the window to stop it",
  );
  // pytest under a make check started in a terminal (process group 61000)
  await page.getByRole("button", { name: /Stop pid 61002/ }).click();
  const dialog = page.getByRole("dialog", { name: "Stop pid 61002?" });
  await expect(dialog).toContainText("Its whole process group (4 processes)");
  await expect(dialog).toContainText("61000");
  await expect(dialog).toContainText("It and its children (2 processes)");
  await expect(dialog).toContainText("Another session may be using them");
  await dialog.getByRole("radio", { name: /It and its children/ }).check();
  const sent = page.waitForRequest((r) => r.url().includes("/api/processes/61002/stop"));
  await dialog.getByRole("button", { name: "Stop them" }).click();
  const stop = (await sent).postDataJSON();
  expect(stop.mode).toBe("tree");
  expect(stop.confirm_token).toMatch(/^c-/);
});

test("what Claude Code runs is named but never stopped from here", async ({ page, request }) => {
  await setWorld(request, { world: { ...RUNNING, sessions: "agent" } });
  await openApp(page, "processes");
  const row = page.locator("tr", { has: page.locator("th code", { hasText: /^61002$/ }) });
  await expect(row).toContainText("Claude Code runs it; stop it there");
  await expect(row).toContainText("Claude's build agent");
  await expect(page.getByRole("button", { name: /Stop pid 6100\d/ })).toHaveCount(0);
});

test("a control window cannot be stopped from here, and it says why", async ({ page }) => {
  test.skip(!isMock(), "the demo helper runs no other control window");
  await openApp(page, "processes");
  await page.getByRole("button", { name: /Stop pid 5120/ }).click();
  const dialog = page.getByRole("dialog", { name: "Pid 5120 cannot be stopped from here" });
  await expect(dialog).toContainText("that is a control panel window");
  await expect(dialog.getByRole("button", { name: "Stop them" })).toHaveCount(0);
});
