// The first-launch tour: five steps, skippable, remembered, and replayable from the Guide.

import { baseUrl, expect, launchUrl, openApp, setWorld, test, token } from "./helpers.mjs";

test("the tour runs on the first launch, and is remembered once done", async ({
  page,
  request,
}) => {
  await setWorld(request, { reset: true, prefs: { tour_done: false } });
  await openApp(page);
  const steps = [
    "Start and stop everything here",
    "See what is running",
    "How the parts connect",
    "Find any action",
    "Help in plain words",
  ];
  for (const [index, title] of steps.entries()) {
    const card = page.getByRole("dialog", { name: title });
    await expect(card).toBeVisible();
    await expect(card).toContainText(`${index + 1} of 5`);
    await card.getByRole("button", { name: index === 4 ? "Done" : "Next" }).click();
  }
  await expect(page.locator(".tour-layer")).toHaveCount(0);
  const prefs = await request.get(`${baseUrl()}/api/prefs`, {
    headers: { "X-Panel-Token": token() },
  });
  expect(await prefs.json()).toMatchObject({ tour_done: true });
  // a plain reload has no launch code (the app shell reloads with a new one): the window says so
  await page.reload();
  await expect(page.getByRole("heading", { name: "Open this window from the app" })).toBeVisible();
  // a new window with a fresh launch code does not show the tour again
  const again = await page.context().newPage();
  await again.goto(await launchUrl(request));
  await expect(again.locator(".view[data-view='home']")).toBeVisible();
  await again.waitForTimeout(900);
  await expect(again.locator(".tour-layer")).toHaveCount(0);
});

test("the tour can be skipped with Escape and moved with the arrow keys", async ({
  page,
  request,
}) => {
  await setWorld(request, { reset: true, prefs: { tour_done: false } });
  await openApp(page);
  await expect(page.getByRole("dialog", { name: "Start and stop everything here" })).toBeVisible();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("dialog", { name: "See what is running" })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("dialog", { name: "Start and stop everything here" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".tour-layer")).toHaveCount(0);
});

test("the Guide replays the tour", async ({ page, request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true } });
  await openApp(page, "guide");
  await page.getByRole("button", { name: "Take the tour" }).first().click();
  const card = page.getByRole("dialog", { name: "Start and stop everything here" });
  await expect(card).toBeVisible();
  await expect(page.locator(".view[data-view='home']")).toBeVisible();
  await card.getByRole("button", { name: "Skip the tour" }).click();
  await expect(page.locator(".tour-layer")).toHaveCount(0);
});
