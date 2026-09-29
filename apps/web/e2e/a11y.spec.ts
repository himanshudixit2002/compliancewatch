import { SCREENS, hrefFor, isCatchAll, routeParams } from "../src/shared/config/screens.ts";
import type { Screen } from "../src/shared/config/screens.ts";
import { expect, test } from "./fixtures";

/**
 * Every page in the registry, visited without a session: the live public pages by their route,
 * and every planned, waiting or ready page through the catch-all with "example" for each
 * parameter. The legal documents have their own spec (an "example" document is a 404 by design).
 */
function exampleHref(screen: Screen): string {
  const params = Object.fromEntries(routeParams(screen.route).map((name) => [name, "example"]));
  return hrefFor(screen, params);
}

const PAGES = SCREENS.filter(
  (screen) => screen.kind === "page" && !isCatchAll(screen.route) && screen.id !== "system.legal",
);

test.describe("every registered page", () => {
  for (const screen of PAGES) {
    test(`${screen.id} (${screen.status}) renders with one h1 and no serious axe finding`, async ({
      page,
      checkA11y,
    }) => {
      const response = await page.goto(exampleHref(screen));
      expect(response?.status(), screen.route).toBe(200);
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      if (screen.status !== "live") {
        await expect(page.getByText("Not available yet")).toBeVisible();
        await expect(page.getByRole("heading", { level: 1, name: screen.title })).toBeVisible();
      }
      await checkA11y();
    });
  }
});
