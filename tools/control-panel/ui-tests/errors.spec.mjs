// Errors are plain words with a fix and the action that applies it, and the technical lines one
// click away.

import { confirmIfAsked, expect, openApp, setWorld, test, token } from "./helpers.mjs";

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true }, speed: 3 });
});

test("Docker not running: the reason, the fix button and the details", async ({
  page,
  request,
}) => {
  await setWorld(request, {
    failNext: {
      action: "start-everything",
      step: 1,
      lines: [
        "Cannot connect to the Docker daemon at unix:///Users/me/.colima/default/docker.sock. Is the docker daemon running?",
        "make: *** [dev] Error 1",
      ],
    },
  });
  await openApp(page);
  await page.getByRole("button", { name: "Start everything" }).first().click();
  await confirmIfAsked(page);
  const hero = page.locator(".hero");
  await expect(hero).toHaveAttribute("data-state", "failed", { timeout: 15000 });
  await expect(
    hero.getByRole("heading", { name: "Start everything did not finish" }),
  ).toBeVisible();
  await expect(hero.locator(".run-headline")).toHaveText("Docker is not running");
  await expect(hero.locator(".run-fix")).toContainText("Start Docker, then try again.");
  await expect(hero.getByRole("button", { name: "Start Docker" })).toBeVisible();
  await expect(hero.getByRole("button", { name: "Try again" })).toBeVisible();
  await hero.getByRole("button", { name: "Show technical details" }).click();
  await expect(hero.locator(".run-failure .code-block")).toContainText(
    "Cannot connect to the Docker daemon",
  );
  const toast = page.locator(".toast.tone-danger", { hasText: "Docker is not running" });
  await expect(toast).toBeVisible();
  await expect(toast.getByRole("button", { name: "Start Docker" })).toBeVisible();
  await hero.getByRole("button", { name: "Start Docker" }).click();
  await expect(page.locator(".toast", { hasText: "Start Docker: done" })).toBeVisible({
    timeout: 15000,
  });
});

test("a stop that times out offers the force stop as its own question", async ({
  page,
  request,
}) => {
  await setWorld(request, {
    world: { docker: true, infra: true, services: 10, web: true },
    failNext: { action: "stop-everything", step: 5, state: "timeout", lines: ["colima stop ..."] },
  });
  await openApp(page);
  await page.getByRole("button", { name: "Stop everything" }).first().click();
  await page
    .getByRole("dialog", { name: "Stop everything?" })
    .getByRole("button", { name: "Stop everything" })
    .click();
  const hero = page.locator(".hero");
  await expect(hero.locator(".run-headline")).toHaveText("Docker did not stop in time", {
    timeout: 15000,
  });
  await expect(hero.locator(".run-step[data-state='timeout']")).toContainText("timed out");
  await hero.getByRole("button", { name: "Force-stop Docker" }).click();
  const dialog = page.getByRole("dialog", { name: "Force-stop Docker?" });
  await expect(dialog).toContainText("The databases get no time to close their files.");
  await expect(dialog.getByRole("button", { name: "Force-stop Docker" })).toBeDisabled();
  await dialog.getByRole("checkbox", { name: /I understand/ }).check();
  await expect(dialog.getByRole("button", { name: "Force-stop Docker" })).toBeEnabled();
  await dialog.getByRole("button", { name: "Cancel" }).click();
});

test("an action that needs something else says what, before you press it", async ({ page }) => {
  await openApp(page, "data");
  const card = page.locator("#action-product-seed");
  await expect(card.getByRole("button", { name: "Fill" })).toBeDisabled();
  await expect(card.locator(".ac-reason")).toContainText("The product is not running.");
  await expect(card.locator(".ac-fix")).toHaveText("Start the product");
});

test("a refused request says why in plain words", async ({ page, request }) => {
  await setWorld(request, { speed: 0.25, world: { docker: true, infra: true } });
  await openApp(page);
  // a second step sent while one runs: the helper answers 409 busy
  await page.evaluate(async (t) => {
    const post = (id) =>
      fetch(`/api/actions/${id}/run`, {
        method: "POST",
        headers: { "X-Panel-Token": t, "Content-Type": "application/json" },
        body: JSON.stringify({ params: {}, confirm: false }),
      });
    await post("databases-start");
  }, token());
  await page.locator("#activity-btn").click();
  await page.keyboard.press("Escape");
  await page.keyboard.press("Meta+k");
  await page.keyboard.type("start docker");
  await page.keyboard.press("Enter");
  await expect(page.locator(".toast", { hasText: "Start Docker cannot run now" })).toContainText(
    'Waits for "Start the databases" to finish',
  );
});

test("a window without a valid key says how to get one", async ({ page }) => {
  await page.goto(`${process.env.PANEL_URL}/#launch=l-not-a-code-of-this-helper`);
  await expect(page.getByRole("heading", { name: "Open this window from the app" })).toBeVisible();
  expect(page.url()).not.toContain("launch=");
});
