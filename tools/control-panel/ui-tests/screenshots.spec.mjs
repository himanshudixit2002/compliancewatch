// Light and dark screenshots of every view, and of the palette, a confirm, the Activity sheet and
// the tour, saved to var/screenshots for review. Each view is shot at 1100x760 (as the window
// opens) and at its full height (-full).

import { confirmIfAsked, expect, openApp, setWorld, SHOTS, test, VIEWS } from "./helpers.mjs";

const RUNNING = {
  reset: true,
  prefs: { tour_done: true },
  world: {
    docker: true,
    infra: true,
    services: 10,
    web: true,
    product: { internal: true, public: true, worker: true, web: true },
    background: { "worker-pipeline": 70112, "relay-obligation": 70140 },
  },
};

async function shoot(page, name, { full = true } = {}) {
  await page.evaluate(() => document.querySelectorAll(".toast").forEach((toast) => toast.remove()));
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${SHOTS}${name}.png` });
  if (!full) return;
  const height = await page.evaluate(() => {
    const main = document.getElementById("main");
    return Math.min(3200, Math.max(760, main.scrollHeight + main.getBoundingClientRect().top + 8));
  });
  const size = page.viewportSize();
  await page.setViewportSize({ width: size.width, height });
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${SHOTS}${name}-full.png` });
  await page.setViewportSize(size);
}

for (const scheme of ["light", "dark"]) {
  test.describe(`${scheme} scheme`, () => {
    test.use({ colorScheme: scheme });

    test(`every view, ${scheme}`, async ({ page, request }) => {
      test.setTimeout(120000);
      await setWorld(request, RUNNING);
      await openApp(page);
      // a little history, so Recent activity and Checks have something to show
      await page.evaluate(async (tokenValue) => {
        const run = (id) =>
          fetch(`/api/actions/${id}/run`, {
            method: "POST",
            headers: { "X-Panel-Token": tokenValue, "Content-Type": "application/json" },
            body: JSON.stringify({ params: {}, confirm: false }),
          });
        await run("gate:lint");
      }, process.env.PANEL_TOKEN);
      await expect(page.locator(".recent-item").first()).toBeVisible({ timeout: 15000 });
      await page.waitForFunction(
        () => !document.querySelector(".recent-item[data-state='running']"),
        null,
        { timeout: 15000 },
      );
      for (const [view] of VIEWS) {
        await page.evaluate((v) => (window.location.hash = `#/${v}`), view);
        await expect(page.locator(`.view[data-view='${view}']`)).toBeVisible();
        if (view === "logs")
          await expect(page.locator(".log-link[aria-current='page']")).toBeVisible();
        await shoot(page, `${view}-${scheme}`);
      }
      for (const section of ["parts", "recipes", "glossary", "trouble", "never"]) {
        await page.evaluate((s) => (window.location.hash = `#/guide/${s}`), section);
        await page.waitForTimeout(150);
        await shoot(page, `guide-${section}-${scheme}`);
      }
    });

    test(`home while stopped and starting, ${scheme}`, async ({ page, request }) => {
      await setWorld(request, { reset: true, prefs: { tour_done: true }, speed: 0.4 });
      await openApp(page);
      await expect(page.locator(".hero")).toHaveAttribute("data-state", "stopped");
      await shoot(page, `home-stopped-${scheme}`, { full: false });
      await page.getByRole("button", { name: "Start everything" }).first().click();
      await confirmIfAsked(page);
      await expect(page.locator(".hero[data-state='starting']")).toBeVisible();
      await page.waitForTimeout(1600);
      await shoot(page, `home-starting-${scheme}`, { full: false });
      await setWorld(request, { speed: 3 });
    });

    test(`palette, confirm, activity and tour, ${scheme}`, async ({ page, request }) => {
      await setWorld(request, {
        ...RUNNING,
        world: { ...RUNNING.world, branch: "pipeline-ops", sessions: "agent" },
      });
      await openApp(page);
      await page.keyboard.press("Meta+k");
      await page.keyboard.type("back");
      await shoot(page, `palette-${scheme}`, { full: false });
      await page.keyboard.press("Escape");
      await page.getByRole("button", { name: "Stop everything" }).first().click();
      await expect(page.getByRole("dialog", { name: "Stop everything?" })).toBeVisible();
      await shoot(page, `confirm-stop-${scheme}`, { full: false });
      await page.getByRole("button", { name: "Cancel" }).click();
      await page.evaluate(() => (window.location.hash = "#/data"));
      await page.locator("#action-reset").getByRole("button", { name: "Reset" }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await shoot(page, `confirm-reset-${scheme}`, { full: false });
      await page.getByRole("button", { name: "Cancel" }).click();
      // a finished backup, so the sheet shows a run with its steps and output
      await page.evaluate(async (tokenValue) => {
        await fetch("/api/actions/backup/run", {
          method: "POST",
          headers: { "X-Panel-Token": tokenValue, "Content-Type": "application/json" },
          body: JSON.stringify({ params: {} }),
        });
      }, process.env.PANEL_TOKEN);
      await expect(page.locator("#activity-btn")).toHaveAttribute("data-state", "running");
      await expect(page.locator("#activity-btn")).not.toHaveAttribute("data-state", "running", {
        timeout: 20000,
      });
      await page.locator("#activity-btn").click();
      await expect(page.getByRole("dialog", { name: "Activity" }).getByRole("log")).toBeVisible();
      await shoot(page, `activity-${scheme}`, { full: false });
      await page.keyboard.press("Escape");
      await page.evaluate(() => (window.location.hash = "#/guide/more"));
      await page.getByRole("button", { name: "Take the tour" }).first().click();
      await expect(
        page.getByRole("dialog", { name: "Start and stop everything here" }),
      ).toBeVisible();
      await shoot(page, `tour-${scheme}`, { full: false });
      await page.getByRole("button", { name: "Skip the tour" }).click();
    });
  });
}

test("the pipeline's tables at 1280 px", async ({ page, request }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await setWorld(request, RUNNING);
  await openApp(page, "pipeline");
  await expect(page.locator(".view .stamp").first()).toContainText(/Read (just now|\d)/);
  await shoot(page, "pipeline-1280-light");
});

test("the narrowest window, 900x600", async ({ page, request }) => {
  await page.setViewportSize({ width: 900, height: 600 });
  await setWorld(request, RUNNING);
  await openApp(page);
  await shoot(page, "home-900x600-light", { full: false });
  await page.evaluate(() => (window.location.hash = "#/run"));
  await shoot(page, "run-900x600-light", { full: false });
  await page.evaluate(() => (window.location.hash = "#/guide/recipes"));
  await shoot(page, "guide-recipes-900x600-light", { full: false });
});
