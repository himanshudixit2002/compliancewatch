// The window paints at once, nothing on it jumps while the data arrives, and a press is
// acknowledged within 100 ms.

import { expect, launchUrl, setWorld, test } from "./helpers.mjs";

test.beforeEach(async ({ request }) => {
  await setWorld(request, {
    reset: true,
    prefs: { tour_done: true },
    world: { docker: true, infra: true, services: 10, web: true },
  });
});

test("first paint comes under 300 ms and the layout does not shift", async ({ page }) => {
  await page.addInitScript(() => {
    window.__shift = 0;
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries())
        if (!entry.hadRecentInput) window.__shift += entry.value;
    }).observe({ type: "layout-shift", buffered: true });
  });
  await page.goto(await launchUrl(page.request));
  await expect(page.locator(".hero[data-state='running']")).toBeVisible();
  await page.waitForTimeout(800);
  const paint = await page.evaluate(
    () => performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? Infinity,
  );
  const shift = await page.evaluate(() => window.__shift);
  console.log(`first contentful paint ${paint.toFixed(0)} ms, layout shift ${shift.toFixed(3)}`);
  expect(paint).toBeLessThan(300);
  expect(shift).toBeLessThan(0.1);
});

test("a press is acknowledged within 100 ms", async ({ page }) => {
  await page.goto(await launchUrl(page.request));
  await page.evaluate(() => (window.location.hash = "#/data"));
  const button = page.locator("#action-backup").getByRole("button", { name: "Back up" });
  await expect(button).toBeEnabled();
  const elapsed = await button.evaluate(
    (el) =>
      new Promise((resolve) => {
        const card = el.closest(".action-card");
        const started = performance.now();
        const observer = new MutationObserver(() => {
          if (el.getAttribute("aria-busy") !== null || card.dataset.state === "running") {
            observer.disconnect();
            resolve(performance.now() - started);
          }
        });
        observer.observe(card, { attributes: true, subtree: true });
        el.click();
      }),
  );
  console.log(`acknowledged in ${elapsed.toFixed(1)} ms`);
  expect(elapsed).toBeLessThan(100);
});
