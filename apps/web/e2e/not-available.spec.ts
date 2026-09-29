import { expect, test } from "./fixtures";

test.describe("not available yet", () => {
  test("an admin tool shows its awaited routes, owner and breadcrumbs", async ({
    page,
    checkA11y,
  }) => {
    await page.goto("/admin/review/stats");
    await expect(page.getByRole("heading", { level: 1, name: "Review stats" })).toBeVisible();
    await expect(page.getByText("GET /v1/rulebook/review/stats")).toBeVisible();
    await expect(page.getByText("KAG track")).toBeVisible();
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
    checkA11y,
  }) => {
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

  test("a planned tool says no backend exists and shows its note", async ({ page }) => {
    await page.goto("/admin/backfill");
    await expect(
      page.getByRole("heading", { level: 1, name: "Backfill and replay" }),
    ).toBeVisible();
    await expect(page.getByText("POST /v1/pipeline/backfills")).toBeVisible();
    await expect(page.getByText("not scheduled", { exact: false }).first()).toBeVisible();
    await expect(page.getByText(/make backfill/)).toBeVisible();
  });

  test("unknown paths are real 404s under both shells", async ({ page }) => {
    for (const path of ["/nowhere", "/admin/nowhere", "/b/example/nope"]) {
      const response = await page.goto(path);
      expect(response?.status(), path).toBe(404);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });
});
