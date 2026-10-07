import { SCREENS, hrefFor, routeParams } from "../src/shared/config/screens.ts";
import { ADMIN, ANALYST, OWNER, expect, personaFor, test } from "./fixtures";

/**
 * A tenant page with parameters that is not built yet, while the registry still has one. The
 * catch-all serves it with "example" for each parameter. Picked from the registry so the spec
 * does not break each time a backend lands and the screen moves on.
 */
const UNBUILT_TENANT_PAGE_WITH_PARAMETERS = SCREENS.find(
  (screen) =>
    screen.kind === "page" &&
    (screen.section === "owner" || screen.section === "ca") &&
    screen.status !== "live" &&
    routeParams(screen.route).length > 0,
);

test.describe("not available yet", () => {
  test("an admin tool shows its awaited routes, owner and breadcrumbs", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await page.goto("/admin/error-reports");
    await expect(page.getByRole("heading", { level: 1, name: "Error reports" })).toBeVisible();
    await expect(page.getByText("GET /v1/rulebook/error-reports")).toBeVisible();
    await expect(page.getByText("services track (WP24)").first()).toBeVisible();
    const crumbs = page.getByRole("navigation", { name: "Breadcrumb" });
    await expect(crumbs.getByRole("link", { name: "Internal tools" })).toHaveAttribute(
      "href",
      "/admin",
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
    const screen = UNBUILT_TENANT_PAGE_WITH_PARAMETERS;
    test.skip(screen === undefined, "every tenant page with parameters is built");
    if (screen === undefined) return;
    await signIn(personaFor(screen) ?? OWNER);
    const params = Object.fromEntries(routeParams(screen.route).map((name) => [name, "example"]));
    await page.goto(hrefFor(screen, params));
    await expect(page.getByRole("heading", { level: 1, name: screen.title })).toBeVisible();
    const route = screen.awaits[0] ?? screen.uses[0];
    if (route !== undefined) {
      await expect(page.getByText(`${route.method} ${route.path}`).first()).toBeVisible();
    }
    await expect(page.getByRole("link", { name: "Back", exact: true })).toBeVisible();
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
    // Internal users is an admin-only tool: an analyst gets a 404 there.
    await signIn(ADMIN);
    await page.goto("/admin/team");
    await expect(page.getByRole("heading", { level: 1, name: "Internal users" })).toBeVisible();
    await expect(page.getByText("Not available yet")).toBeVisible();
    await expect(
      page.getByText(
        "The backend for this screen is on main. The screen itself has not been built yet.",
      ),
    ).toBeVisible();
    await expect(page.getByText("GET /v1/identity/users", { exact: true })).toBeVisible();
    await expect(page.getByText("services track (WP14)").first()).toBeVisible();
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
