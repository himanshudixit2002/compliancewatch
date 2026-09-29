import { expect, test } from "./fixtures";

test.describe("design catalogue", () => {
  test("renders every group and each one passes axe", async ({ page, checkA11y }) => {
    await page.goto("/design");
    await expect(page.getByRole("heading", { level: 1, name: "Design system" })).toBeVisible();
    const sections = page.locator("[data-catalogue-section]");
    const count = await sections.count();
    expect(count).toBeGreaterThanOrEqual(9);
    for (let index = 0; index < count; index += 1) {
      const id = await sections.nth(index).getAttribute("data-catalogue-section");
      await expect(sections.nth(index), id ?? "").toBeVisible();
      await checkA11y(`[data-catalogue-section="${id}"]`);
    }
  });

  test("the theme control forces dark and light on the document", async ({ page }) => {
    await page.goto("/design");
    await page.getByRole("button", { name: "Dark" }).click();
    await expect(page.locator("html")).toHaveClass(/\bdark\b/);
    await page.getByRole("button", { name: "Light" }).click();
    await expect(page.locator("html")).toHaveClass(/\blight\b/);
    await expect(page.locator("html")).not.toHaveClass(/\bdark\b/);
    await page.getByRole("button", { name: "System" }).click();
    await expect(page.locator("html")).not.toHaveClass(/\b(light|dark)\b/);
  });

  test("dialogs open, trap focus and close on Escape", async ({ page, checkA11y }) => {
    await page.goto("/design");
    await page.getByRole("button", { name: "Open dialog" }).click();
    const dialog = page.getByRole("dialog", { name: "Example dialog" });
    await expect(dialog).toBeVisible();
    await checkA11y("[role='dialog']");
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await page.getByRole("button", { name: "Open reason dialog" }).click();
    const reject = page.getByRole("button", { name: "Reject" });
    await expect(reject).toBeDisabled();
    await page.getByRole("textbox", { name: /Reason/ }).fill("Example reason text");
    await expect(reject).toBeEnabled();
    await reject.click();
    await expect(page.getByRole("dialog")).toBeHidden();
  });

  test("the calendar moves focus with the arrow keys", async ({ page }) => {
    await page.goto("/design");
    const grid = page.getByRole("grid", { name: "January 2000" });
    await grid.locator("[data-key='2000-01-15']").focus();
    await page.keyboard.press("ArrowRight");
    await expect(grid.locator("[data-key='2000-01-16']")).toBeFocused();
    await page.keyboard.press("ArrowDown");
    await expect(grid.locator("[data-key='2000-01-23']")).toBeFocused();
  });
});
