import { LEGAL_DOCS } from "../src/shared/config/legal-docs.ts";
import { expect, test } from "./fixtures";

const DRAFT_BANNER_TEXT = "Draft - to be reviewed by a lawyer";

test.describe("legal documents", () => {
  for (const doc of LEGAL_DOCS) {
    test(`${doc.name} renders under the draft banner`, async ({ page, checkA11y }) => {
      await page.goto(`/legal/${doc.name}`);
      await expect(page.getByRole("status").filter({ hasText: DRAFT_BANNER_TEXT })).toBeVisible();
      await expect(page.getByText(/Version \S+-draft/)).toBeVisible();
      await expect(page.getByRole("heading", { level: 1 })).toHaveText(doc.title);
      await checkA11y();
    });
  }

  test("a document that is not published is a 404", async ({ page }) => {
    const response = await page.goto("/legal/data-map");
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  });
});
