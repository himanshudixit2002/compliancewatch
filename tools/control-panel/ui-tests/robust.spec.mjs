// What a hurried person or a slow helper should never break: an event that lands while a read
// is on its way, two quick clicks, and tables that are wider than their card.

import { baseUrl, expect, openApp, setWorld, test } from "./helpers.mjs";

const RUNNING = {
  docker: true,
  infra: true,
  services: 10,
  web: true,
  product: { internal: true, public: true, worker: true, web: true },
};

test.beforeEach(async ({ request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true }, world: RUNNING });
});

test("a features event that lands mid-read is not lost", async ({ page }) => {
  // every read answers late, so the helper's features event arrives while one is on its way
  await page.route("**/api/features", async (route) => {
    const response = await route.fetch();
    await new Promise((done) => setTimeout(done, 700));
    await route.fulfill({ response });
  });
  await openApp(page, "features");
  await expect(page.locator(".feature").first()).toBeVisible({ timeout: 10000 });
  await expect(page.locator(".view .stamp")).toContainText(/^Read (just now|\d)/);
});

test("one read at a time, and a call that comes mid-read makes exactly one more", async ({
  page,
}) => {
  await openApp(page);
  const result = await page.evaluate(async () => {
    const { oneAtATime } = await import("/dom.js");
    const calls = [];
    const slow = (tag) =>
      new Promise((done) =>
        setTimeout(() => {
          calls.push(tag);
          done(tag);
        }, 60),
      );
    const read = oneAtATime(slow);
    const answers = await Promise.all([read("first"), read("event 1"), read("event 2")]);
    await read("later");
    return { answers, calls };
  });
  expect(result.answers).toEqual(["first", "event 2", "event 2"]);
  expect(result.calls).toEqual(["first", "event 2", "later"]);
});

test("two quick clicks open one question", async ({ page }) => {
  const previews = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/actions/stop-everything/preview")) previews.push(r.url());
  });
  await openApp(page);
  await page.getByRole("button", { name: "Stop everything" }).first().dblclick();
  const dialog = page.getByRole("dialog", { name: "Stop everything?" });
  await expect(dialog).toBeVisible();
  await page.waitForTimeout(600);
  await expect(page.getByRole("dialog")).toHaveCount(1);
  expect(previews).toHaveLength(1);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
});

test("two quick clicks on a safe action start it once", async ({ page, request }) => {
  await setWorld(request, { speed: 0.2 });
  const starts = [];
  page.on("request", (r) => {
    if (r.method() === "POST" && /\/api\/actions\/gate(:|%3A)lint\/run$/.test(r.url()))
      starts.push(r.url());
  });
  await openApp(page, "checks");
  const card = page.locator("[id='action-gate:lint']");
  await card.getByRole("button", { name: "Check" }).dblclick();
  await expect(card).toHaveAttribute("data-state", "running");
  await page.waitForTimeout(600);
  expect(starts).toHaveLength(1);
  await expect(page.locator(".toast", { hasText: "running" })).toHaveCount(0);
});

test("a stop of a process asks once, however fast the clicks", async ({ page, request }) => {
  await setWorld(request, { world: { ...RUNNING, sessions: "terminal" } });
  await openApp(page, "processes");
  await page.getByRole("button", { name: /Stop pid 61002/ }).dblclick();
  await expect(page.getByRole("dialog", { name: "Stop pid 61002?" })).toBeVisible();
  await page.waitForTimeout(600);
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await page.getByRole("dialog").getByRole("button", { name: "Cancel" }).click();
});

for (const width of [1280, 1100, 900]) {
  test(`the tables fit their cards at ${width} px, and the page never scrolls sideways`, async ({
    page,
    request,
  }) => {
    await setWorld(request, { world: { ...RUNNING, sessions: "agent" } });
    await page.setViewportSize({ width, height: 800 });
    await openApp(page, "pipeline");
    await expect(page.locator(".view .stamp").first()).toContainText(/Read (just now|\d)/);
    await expect(page.getByRole("table", { name: "Consumer groups and their lag" })).toBeVisible();
    for (const view of ["pipeline", "processes", "flags", "commands", "logs"]) {
      if (view !== "pipeline") {
        await page.evaluate((v) => (window.location.hash = `#/${v}`), view);
        await expect(page.locator(`.view[data-view='${view}']`)).toBeVisible();
        await page.waitForTimeout(300);
      }
      const fit = await page.evaluate(() => ({
        page: document.documentElement.scrollWidth - window.innerWidth,
        main:
          document.getElementById("main").scrollWidth - document.getElementById("main").clientWidth,
        tables: [...document.querySelectorAll(".events-grid .table-wrap")].map(
          (el) => el.scrollWidth - el.clientWidth,
        ),
      }));
      expect(fit.page, `${view}: the page scrolls sideways`).toBeLessThanOrEqual(0);
      expect(fit.main, `${view}: the content scrolls sideways`).toBeLessThanOrEqual(0);
      for (const over of fit.tables)
        expect(over, `${view}: a table is wider than its card`).toBeLessThanOrEqual(1);
    }
  });
}

test("the helper serves every file of the window to many requests at once", async ({ request }) => {
  // the window asks for its ~25 modules together; none of them may be dropped
  const files = [
    "index.html",
    "app.css",
    "app.js",
    "api.js",
    "actions.js",
    "model.js",
    "store.js",
    "dom.js",
    "ui.js",
    "icons.js",
    "guide.js",
    "palette.js",
    "tour.js",
    "activity.js",
    "boot.js",
    "views/home.js",
    "views/run.js",
    "views/data.js",
    "views/checks.js",
    "views/features.js",
    "views/pipeline.js",
    "views/flags.js",
    "views/processes.js",
    "views/logs.js",
    "views/commands.js",
    "views/guide.js",
    "views/common.js",
  ];
  for (let round = 0; round < 3; round += 1) {
    const answers = await Promise.all(
      files.map((file) =>
        request
          .get(`${baseUrl()}/${file}`)
          .then((r) => r.status())
          .catch((error) => String(error.message).split("\n")[0]),
      ),
    );
    expect(answers.filter((status) => status !== 200)).toEqual([]);
  }
});
