import { ADMIN, expect, signInThroughForm, test } from "./fixtures";

/**
 * The /admin allow-list (src/proxy.ts): the e2e server runs with 10.0.0.0/8 and trusts the
 * proxy headers, and every request of this project claims 10.0.0.7 (playwright.config.ts). A
 * context from outside the list sees the forbidden page on every admin path, in the browser
 * and as a fetch, while the rest of the app stays open; x-real-ip wins over x-forwarded-for.
 */
test.describe("admin allow-list", () => {
  test("an address outside the list sees the forbidden page on every admin path", async ({
    browser,
    baseURL,
  }) => {
    const outside = await browser.newContext({
      baseURL,
      extraHTTPHeaders: { "x-forwarded-for": "203.0.113.9, 10.0.0.7" },
    });
    try {
      const page = await outside.newPage();
      await signInThroughForm(page, ADMIN, "/account");
      await expect(page).toHaveURL(/\/account$/);
      for (const path of ["/admin", "/admin/review", "/admin/team", "/admin/nowhere"]) {
        await page.goto(path);
        await expect(page, path).toHaveURL(new RegExp(`${path}$`));
        await expect(
          page.getByRole("heading", { level: 1, name: "You cannot open this page" }),
          path,
        ).toBeVisible();
        await expect(page.getByRole("navigation", { name: "Internal tools" })).toHaveCount(0);
      }
      // A refusal is the proxy's: no admin page ran.
      const response = await page.request.get("/admin", { maxRedirects: 0 });
      expect(response.status()).toBe(200);
      expect(await response.text()).toContain("You cannot open this page");
      expect(await response.text()).not.toContain("Internal tools");
    } finally {
      await outside.close();
    }
  });

  test("x-real-ip names the client before x-forwarded-for, and an untrusted address is none", async ({
    browser,
    baseURL,
  }) => {
    const real = await browser.newContext({
      baseURL,
      extraHTTPHeaders: { "x-real-ip": "10.9.9.9", "x-forwarded-for": "203.0.113.9" },
    });
    try {
      const page = await real.newPage();
      await signInThroughForm(page, ADMIN);
      await expect(page).toHaveURL(/\/admin$/);
      await expect(page.getByRole("heading", { level: 1, name: "Internal tools" })).toBeVisible();
    } finally {
      await real.close();
    }
    const none = await browser.newContext({
      baseURL,
      extraHTTPHeaders: { "x-forwarded-for": "" },
    });
    try {
      const page = await none.newPage();
      await signInThroughForm(page, ADMIN, "/account");
      await page.goto("/admin");
      await expect(
        page.getByRole("heading", { level: 1, name: "You cannot open this page" }),
      ).toBeVisible();
    } finally {
      await none.close();
    }
  });
});
