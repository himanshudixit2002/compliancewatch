// Every view renders, with its title, without a script error, and the sidebar and top bar work.

import { expect, launchUrl, openApp, setWorld, test, token, VIEWS } from "./helpers.mjs";

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true } });
});

for (const [view, title] of VIEWS) {
  test(`${title} renders`, async ({ page }) => {
    const errors = await openApp(page, view);
    await expect(page).toHaveTitle(`${title} · ComplianceWatch Control`);
    await expect(page.locator(".nav-link[aria-current='page']")).toHaveAttribute("data-view", view);
    await expect(page.locator(`.view[data-view='${view}'] h1`)).toHaveText(title);
    await page.waitForTimeout(300);
    expect(errors).toEqual([]);
  });
}

test("no address carries the token; the launch code leaves the address bar", async ({ page }) => {
  const seen = [];
  const urls = [];
  page.on("request", (request) => {
    urls.push(request.url());
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/") && path !== "/api/launch")
      seen.push(request.headers()["x-panel-token"]);
  });
  await openApp(page);
  expect(page.url()).not.toContain("launch=");
  expect(urls.some((url) => url.includes(process.env.PANEL_TOKEN))).toBe(false);
  expect(seen.length).toBeGreaterThan(2);
  expect(seen.every((value) => value === process.env.PANEL_TOKEN)).toBe(true);
});

test("a launch code opens one window, once", async ({ page, request }) => {
  const url = await launchUrl(request);
  await page.goto(url);
  await expect(page.locator(".pill[data-part='docker']")).not.toHaveAttribute(
    "data-state",
    "unknown",
  );
  const again = await page.context().newPage();
  await again.goto(url);
  await expect(again.getByRole("heading", { name: "Open this window from the app" })).toBeVisible();
  await again.close();
});

test("without a token the window says how to open it", async ({ page }) => {
  await page.goto(`${process.env.PANEL_URL}/`);
  await expect(page.getByRole("heading", { name: "Open this window from the app" })).toBeVisible();
});

test("a file that does not arrive loads the window again, once", async ({ page }) => {
  let refused = 0;
  await page.route("**/views/data.js", (route) =>
    refused++ === 0 ? route.abort("connectionreset") : route.continue(),
  );
  await page.goto(await launchUrl(page.request));
  await expect(page.locator(".pill[data-part='docker']")).not.toHaveAttribute(
    "data-state",
    "unknown",
  );
  expect(refused).toBe(2);
  expect(page.url()).not.toContain("launch=");
});

test("a file that never arrives says what to do", async ({ page }) => {
  await page.route("**/views/data.js", (route) => route.abort("connectionreset"));
  await page.goto(await launchUrl(page.request));
  await expect(page.getByRole("heading", { name: "This window could not load" })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Press ⌘R to load it again");
});

test("the top bar fits the narrowest window, whatever it shows", async ({ page, request }) => {
  await setWorld(request, {
    speed: 0.2,
    world: {
      docker: true,
      infra: true,
      services: 10,
      web: true,
      branch: "pipeline-ops-and-a-long-name",
      sessions: "agent",
    },
  });
  await page.setViewportSize({ width: 900, height: 600 });
  await openApp(page);
  await expect(page.locator("#branch-chip")).toHaveAttribute("data-tone", "danger");
  // something running, so Activity shows its progress too
  await page.evaluate(async (t) => {
    await fetch("/api/actions/gate:lint/run", {
      method: "POST",
      headers: { "X-Panel-Token": t, "Content-Type": "application/json" },
      body: JSON.stringify({ params: {} }),
    });
  }, token());
  await expect(page.locator("#activity-btn")).toHaveAttribute("data-state", "running");
  const room = await page.evaluate(() => {
    const pills = document.querySelector(".pills").lastElementChild.getBoundingClientRect();
    const tools = document.querySelector(".topbar-tools").getBoundingClientRect();
    return { between: tools.left - pills.right, right: window.innerWidth - tools.right };
  });
  expect(room.between).toBeGreaterThanOrEqual(0);
  expect(room.right).toBeGreaterThanOrEqual(0);
});

test("the sidebar moves between views and focuses each title", async ({ page }) => {
  await openApp(page);
  await page.getByRole("link", { name: "Checks" }).click();
  await expect(page.locator(".view[data-view='checks'] h1")).toBeFocused();
  await page.goBack();
  await expect(page.locator(".view[data-view='home']")).toBeVisible();
});
