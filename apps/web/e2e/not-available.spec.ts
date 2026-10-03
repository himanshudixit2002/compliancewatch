import { ADMIN, ANALYST, OWNER, expect, test } from "./fixtures";

test.describe("not available yet", () => {
  test("an admin tool shows its awaited routes, owner and breadcrumbs", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await page.goto("/admin/review/stats");
    await expect(page.getByRole("heading", { level: 1, name: "Review stats" })).toBeVisible();
    await expect(page.getByText("GET /v1/rulebook/review/stats")).toBeVisible();
    await expect(page.getByText("services track (WP21)")).toBeVisible();
    const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(crumbs.getByRole("link", { name: "Review queue" })).toHaveAttribute(
      "href",
      "/admin/review",
    );
    await expect(page.getByRole("link", { name: "Back", exact: true })).toHaveAttribute(
      "href",
      "/admin",
    );
    await checkA11y();
  });

  test("a tenant screen with parameters resolves through the catch-all", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(OWNER);
    await page.goto("/b/example/obligations/example");
    await expect(page.getByRole("heading", { level: 1, name: "Obligation" })).toBeVisible();
    await expect(page.getByText("services track (WP23)").first()).toBeVisible();
    await expect(
      page.getByText("POST /v1/obligation/obligations/{obligation_id}/status"),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Back", exact: true })).toHaveAttribute(
      "href",
      "/",
    );
    await checkA11y();
  });

  test("a tenant screen another kind of tenant may not open sends the visitor to /forbidden", async ({
    page,
    signIn,
  }) => {
    await signIn(OWNER);
    await page.goto("/clients");
    await expect(page).toHaveURL(/\/forbidden$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "You cannot open this page" }),
    ).toBeVisible();
  });

  test("a planned tool says no backend exists and shows its note", async ({ page, signIn }) => {
    // Backfill is an admin-only tool: an analyst gets a 404 there.
    await signIn(ADMIN);
    await page.goto("/admin/backfill");
    await expect(
      page.getByRole("heading", { level: 1, name: "Backfill and replay" }),
    ).toBeVisible();
    await expect(page.getByText("POST /v1/pipeline/backfills")).toBeVisible();
    await expect(page.getByText("not scheduled", { exact: false }).first()).toBeVisible();
    await expect(page.getByText(/make backfill/)).toBeVisible();
  });

  test("a ready tool says its backend is on main and lists what it will use", async ({
    page,
    checkA11y,
    signIn,
  }) => {
    await signIn(ANALYST);
    await page.goto("/admin/flags");
    await expect(page.getByRole("heading", { level: 1, name: "Feature flags" })).toBeVisible();
    await expect(page.getByText("Not available yet")).toBeVisible();
    await expect(
      page.getByText(
        "The backend for this screen is on main. The screen itself has not been built yet.",
      ),
    ).toBeVisible();
    await expect(page.getByText("file packages/flags/registry.json")).toBeVisible();
    await expect(page.getByText("services track (WP12)")).toBeVisible();
    await expect(page.getByText("This screen waits for:")).toHaveCount(0);
    await checkA11y();
  });

  test("unknown paths are real 404s under both shells", async ({ page, signIn }) => {
    await signIn(ANALYST);
    for (const path of ["/nowhere", "/admin/nowhere", "/b/example/nope"]) {
      const response = await page.goto(path);
      expect(response?.status(), path).toBe(404);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });

  test("unknown tenant paths are 404s without a session too", async ({ page }) => {
    for (const path of ["/nowhere", "/b/example/nope"]) {
      const response = await page.goto(path);
      expect(response?.status(), path).toBe(404);
    }
  });
});
