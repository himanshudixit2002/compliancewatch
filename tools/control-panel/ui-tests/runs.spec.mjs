// A run shows its progress and its step in words, streams its output, can be cancelled, and
// says when it is done.

import { confirmIfAsked, expect, openApp, setWorld, test } from "./helpers.mjs";

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true }, speed: 3 });
});

test("Start everything streams its steps and output, and can be cancelled", async ({
  page,
  request,
}) => {
  await setWorld(request, { speed: 0.25 });
  await openApp(page);
  await page.getByRole("button", { name: "Start everything" }).first().click();
  expect(await confirmIfAsked(page)).toBe(true); // it migrates the databases: it asks first
  const hero = page.locator(".hero");
  await expect(hero).toHaveAttribute("data-state", "starting");
  await expect(hero.getByRole("heading", { name: "Starting ComplianceWatch" })).toBeVisible();
  await expect(hero.locator(".run-headline")).toContainText("Step 1 of 7: Start Docker");
  await expect(hero.getByRole("progressbar")).toBeVisible();
  await expect(page.locator("#activity-btn")).toContainText("Start everything");

  await hero.getByRole("button", { name: "Show the live output" }).click();
  await expect(hero.getByRole("log")).toContainText("▸ start Docker");
  await expect(hero.locator(".run-headline")).toContainText("Step 2 of 7", { timeout: 15000 });
  await expect(page.locator(".pill[data-part='infra']")).toHaveAttribute("data-state", "busy");

  await hero.getByRole("button", { name: "Cancel" }).click();
  const confirm = page.getByRole("dialog", { name: 'Cancel "Start everything"?' });
  await expect(confirm).toBeVisible();
  await expect(confirm.getByRole("button", { name: "Keep it running" })).toBeFocused();
  await confirm.getByRole("button", { name: "Cancel it" }).click();
  await expect(page.locator(".toast", { hasText: "Start everything: cancelled" })).toBeVisible({
    timeout: 15000,
  });
  await expect(hero).not.toHaveAttribute("data-state", "starting");
  await expect(page.locator("#activity-btn")).not.toHaveAttribute("data-state", "running");
});

test("a finished run says so and offers the next step", async ({ page, request }) => {
  await setWorld(request, { world: { docker: true, infra: true, services: 10, web: true } });
  await openApp(page, "data");
  const card = page.locator("#action-load-demo-data");
  await card.getByRole("button", { name: "Load" }).click();
  expect(await confirmIfAsked(page)).toBe(true);
  await expect(card).toHaveAttribute("data-state", "running");
  await expect(card.getByRole("button", { name: "Cancel" })).toBeVisible();
  const toast = page.locator(".toast", { hasText: "Load demo data: done" });
  await expect(toast).toBeVisible({ timeout: 15000 });
  await expect(toast.getByRole("button", { name: "Open the app" })).toBeVisible();
  await expect(card.locator(".ac-last")).toContainText("done");
});

test("while one step runs, the others wait and say so", async ({ page, request }) => {
  await setWorld(request, {
    speed: 0.25,
    world: { docker: true, infra: true, services: 10, web: true },
  });
  await openApp(page, "run");
  await page.locator("#action-ui-restart").getByRole("button", { name: "Restart" }).click();
  await page
    .getByRole("dialog", { name: "Restart the services?" })
    .getByRole("button", { name: "Restart" })
    .click();
  const other = page.locator("#action-docker-start");
  await expect(other.getByRole("button", { name: "Start" })).toBeDisabled();
  await expect(other.locator(".ac-reason")).toContainText(
    'Waits for "Restart the services" to finish',
  );
  await page.locator("#activity-btn").click();
  const sheet = page.getByRole("dialog", { name: "Activity" });
  await expect(sheet.locator(".activity-row.open")).toContainText("Restart the services");
  await expect(sheet.getByRole("log")).toBeVisible();
  await page.keyboard.press("Escape");
});
