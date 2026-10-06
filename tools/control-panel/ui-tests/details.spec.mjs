// What each view does beyond rendering: Features, Flags, Logs, Commands, Pipeline and the Guide.

import { confirmIfAsked, expect, openApp, setWorld, test } from "./helpers.mjs";

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

test("Features shows each feature's state, its pages, and what is not built yet", async ({
  page,
}) => {
  await openApp(page, "features");
  const cards = page.locator(".feature");
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThan(5);
  await expect(page.locator(".feature-links a.chip-link").first()).toHaveAttribute(
    "href",
    /^http:\/\/127\.0\.0\.1:3400\/admin\//,
  );
  await expect(page.locator(".chip-link.is-off").first()).toContainText("not built yet");
  await expect(page.locator(".feature[data-state='not-built']").first()).toContainText(
    "Not built yet",
  );
  const review = page.locator(".feature", { hasText: "Review queue" });
  await expect(review.locator(".number").first()).toContainText("Waiting");
});

test("Features asks to start the product when it is not running", async ({ page, request }) => {
  await setWorld(request, { reset: true, prefs: { tour_done: true } });
  await openApp(page, "features");
  await expect(page.locator(".feature-notice")).toContainText("The product is not running");
  await expect(page.getByRole("button", { name: "Start the product" })).toBeVisible();
});

test("Flags are read only, in plain words, and searchable", async ({ page }) => {
  await openApp(page, "flags");
  await expect(page.locator(".flag-row").first()).toBeVisible();
  await page.getByRole("searchbox", { name: "Search flags" }).fill("crawl");
  const row = page.locator(".flag-row", { hasText: "pipeline.crawl" });
  await expect(row).toContainText("reads the live regulator websites");
  await expect(row).toContainText("Off");
  await row.getByRole("button", { name: "pipeline.crawl" }).click();
  await expect(page.locator(".flag-detail:not([hidden])")).toContainText(
    "CW_PIPELINE_CRAWL_ENABLED",
  );
  await expect(page.locator(".view[data-view='flags'] input[type=checkbox]")).toHaveCount(0);
});

test("Logs shows a bounded tail, filters it and copies it", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await openApp(page, "logs");
  await expect(page.locator(".log-link[aria-current='page']")).toBeVisible();
  const lines = page.locator(".output-body .ln");
  await expect(page.getByRole("log")).toContainText("GET /health");
  const total = await lines.count();
  await page.getByRole("searchbox", { name: "Find in this log" }).fill("health");
  await expect.poll(() => lines.count()).toBeLessThan(total);
  for (const text of await lines.allTextContents()) expect(text.toLowerCase()).toContain("health");
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toContain("health");
  const other = page.locator(".log-link").nth(1);
  const label = (await other.textContent()).trim();
  await other.click();
  await expect(page.locator(".log-title")).toHaveText(label);
});

test("Commands lists every action, searchable, with disabled ones saying why", async ({ page }) => {
  await openApp(page, "commands");
  await page.getByRole("searchbox", { name: "Search every action" }).fill("restore");
  await expect(page.locator("#action-restore")).toBeVisible();
  await expect(page.locator("#action-start-everything")).toBeHidden();
  await page.getByRole("searchbox", { name: "Search every action" }).fill("backfill");
  const card = page.locator("[id='action-make:backfill']");
  await expect(card.getByRole("button", { name: "Run" })).toBeDisabled();
  await expect(card.locator(".ac-reason")).toContainText("live regulator websites");
  await page.getByRole("checkbox", { name: "Include make targets" }).uncheck();
  await expect(card).toBeHidden();
});

test("a make target an action covers is found by search, and leads to that action", async ({
  page,
}) => {
  await openApp(page, "commands");
  // make dev is "Start the databases" twice over: only the action is listed
  await expect(page.locator("#action-databases-start")).toBeVisible();
  await expect(page.locator("[id='action-make:dev']")).toBeHidden();
  await page.getByRole("searchbox", { name: "Search every action" }).fill("dev-reset");
  const card = page.locator("[id='action-make:dev-reset']");
  await expect(card).toBeVisible();
  await expect(card.locator(".ac-source")).toContainText("make dev-reset");
  await expect(card.locator(".ac-source")).toContainText(
    "same as “Start fresh (reset the database)”",
  );
  await expect(card.getByRole("button", { name: "Run" })).toBeDisabled();
  await card.getByRole("button", { name: "Go to “Start fresh (reset the database)”" }).click();
  await expect(page.getByRole("searchbox", { name: "Search every action" })).toHaveValue("");
  await expect(page.locator("#action-reset")).toBeInViewport();
  await expect(page.locator("#action-reset [data-role='run']")).toBeFocused();
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("Pipeline and events reads the queue and flags dead letters", async ({ page }) => {
  await openApp(page, "pipeline");
  // a first visit asks for a read at once; wait for it to land, then look at the tables
  const stamp = page.locator(".view .stamp").first();
  await expect(stamp).toContainText(/Read (just now|\d)/);
  await expect(page.getByText("Reading…")).toBeHidden();
  const groups = page.getByRole("table", { name: "Consumer groups and their lag" });
  await expect(groups).toBeVisible();
  await expect(page.locator(".banner.tone-danger")).toContainText(
    "1 dead-letter topic holds messages",
  );
});

test("the Guide's recipes run their steps and open pages", async ({ page }) => {
  await openApp(page, "guide");
  await page.getByRole("link", { name: "Recipes", exact: true }).click();
  const recipe = page.locator("#recipe-see-screens");
  await expect(recipe.locator(".step-done").first()).toBeVisible();
  await expect(
    recipe.getByRole("button", { name: "Open the web app (opens in your browser)" }),
  ).toBeEnabled();
  await expect(page.locator("#recipe-as-ca")).toContainText("00000000-0000-4000-8000-0000000d0002");
  await recipe.getByRole("button", { name: "Load demo data" }).click();
  await confirmIfAsked(page);
  await expect(page.locator(".toast", { hasText: "Load demo data: done" })).toBeVisible({
    timeout: 60000,
  });
});

test("glossary words explain themselves on focus", async ({ page }) => {
  await openApp(page, "run");
  const word = page.locator(".term", { hasText: "Docker" }).first();
  await word.focus();
  await expect(page.getByRole("tooltip")).toContainText(
    "Software that runs programs in containers",
  );
  await expect(word).toHaveAttribute("aria-describedby", "term-tip");
});
