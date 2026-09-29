import { LEGAL_DOCS } from "../src/shared/config/legal-docs.ts";
import { expect, test } from "./fixtures";

const DRAFT_BANNER_TEXT = "Draft - to be reviewed by a lawyer";

test.describe("legal documents", () => {
  for (const doc of LEGAL_DOCS) {
    test(`${doc.name} renders under the draft banner`, async ({ page, checkA11y }) => {
      await page.goto(`/legal/${doc.name}`);
      await expect(page.getByRole("status").filter({ hasText: DRAFT_BANNER_TEXT })).toBeVisible();
      await expect(page.getByText(/Version \S+-draft/).first()).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(doc.title);
      // The line for paper is not shown on screen.
      await expect(page.locator("[data-slot='legal-printed']")).toBeHidden();
      await checkA11y();
    });
  }

  test("a document that is not published is a 404", async ({ page }) => {
    const response = await page.goto("/legal/data-map");
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  });

  test.describe("printed", () => {
    for (const colorScheme of ["light", "dark"] as const) {
      test(`in the ${colorScheme} scheme: without the shell, dark text on white, still a draft`, async ({
        page,
      }) => {
        await page.emulateMedia({ media: "print", colorScheme });
        await page.goto("/legal/privacy-notice");
        await expect(page.locator("[data-slot='app-shell'] > header")).toBeHidden();
        await expect(page.getByRole("link", { name: "Skip to main content" })).toBeHidden();
        await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy notice");
        await expect(page.getByRole("status").filter({ hasText: DRAFT_BANNER_TEXT })).toBeVisible();
        await expect(page.locator("[data-slot='legal-printed']")).toHaveText(
          /^Printed from ComplianceWatch: Privacy notice, version \S+-draft\.$/,
        );
        const colours = await page
          .locator("article p")
          .first()
          .evaluate((element) => {
            const style = getComputedStyle(element);
            return { text: style.color, page: getComputedStyle(document.body).backgroundColor };
          });
        expect(colours).toEqual({ text: "rgb(0, 0, 0)", page: "rgb(255, 255, 255)" });
      });
    }
  });
});
