// The command palette finds actions, places and Guide entries, and runs what it finds.

import { expect, openApp, setWorld, test } from "./helpers.mjs";

const RUNNING = { docker: true, infra: true, services: 10, web: true };

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true }, world: RUNNING });
});

test("⌘K opens the palette and Escape closes it", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Meta+k");
  const palette = page.getByRole("dialog", { name: "Search actions, places and the Guide" });
  await expect(palette).toBeVisible();
  await expect(page.getByRole("combobox")).toBeFocused();
  await expect(palette.getByRole("option").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(palette).toBeHidden();
});

test("the palette finds an action by its plain words and runs it", async ({ page }) => {
  await openApp(page);
  await page.getByRole("button", { name: /Search actions/ }).click();
  await page.keyboard.type("back up");
  const first = page.getByRole("option").first();
  await expect(first).toContainText("Back up the database");
  await expect(page.getByRole("combobox")).toHaveAttribute(
    "aria-activedescendant",
    (await first.getAttribute("id")) ?? "",
  );
  await page.keyboard.press("Enter");
  await expect(page.locator("#activity-btn")).toHaveAttribute("data-state", "running");
  await expect(page.locator(".toast", { hasText: "Back up the database: done" })).toBeVisible({
    timeout: 15000,
  });
});

test("the palette moves with the arrow keys and finds places and Guide entries", async ({
  page,
}) => {
  await openApp(page);
  await page.keyboard.press("Meta+k");
  await page.keyboard.type("glossary docker");
  await expect(page.getByRole("option").first()).toContainText("Docker: what it means");
  await page.keyboard.press("Enter");
  await expect(page.locator(".view[data-view='guide']")).toBeVisible();
  await expect(page.locator("#docker")).toBeFocused();

  await page.keyboard.press("Meta+k");
  await page.keyboard.type("processes");
  const options = page.getByRole("option");
  await expect(options.first()).toContainText("Processes");
  await page.keyboard.press("ArrowDown");
  await expect(options.nth(1)).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page.locator(".view[data-view='processes']")).toBeVisible();
});

test("an action that may not run says why in the palette", async ({ page }) => {
  await openApp(page);
  await page.keyboard.press("Meta+k");
  await page.keyboard.type("backfill");
  const option = page.getByRole("option", { name: /make backfill/ });
  await expect(option).toHaveAttribute("aria-disabled", "true");
  await expect(option).toContainText("It downloads from the live regulator websites");
  await page.keyboard.press("Enter");
  await expect(
    page.locator(".toast", { hasText: "Backfill a regulator source cannot run now" }),
  ).toBeVisible();
});
