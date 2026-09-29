import { ANALYST, OWNER, expect, signInThroughForm, test } from "./fixtures";

test.describe("sign-in", () => {
  test("an anonymous visit to a gated page lands on the form with the path to return to", async ({
    page,
    checkA11y,
  }) => {
    await page.goto("/account");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Faccount$/);
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await expect(page.getByRole("status")).toContainText("Nothing is verified here");
    await expect(page.getByLabel("Tenant kind")).toHaveValue("business");
    await expect(page.getByRole("checkbox", { name: "Owner" })).toBeVisible();
    await expect(page.locator("input[name='next']")).toHaveValue("/account");
    await checkA11y();
  });

  test("the server names each field that fails", async ({ page, checkA11y }) => {
    await page.goto("/sign-in");
    await page.getByLabel("Tenant id").fill("not-a-uuid");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText("Choose at least one role.")).toBeVisible();
    await expect(page.getByText("Enter a display name.")).toBeVisible();
    await expect(page.getByText("Enter a UUID, or leave it empty.")).toBeVisible();
    await expect(page.locator("[data-slot='error-state']")).toContainText(
      "Check the sign-in details",
    );
    await expect(page).toHaveURL(/\/sign-in$/);
    await checkA11y();
  });

  test("an owner signs in, returns to the requested page, sees the account menu and signs out", async ({
    page,
  }) => {
    await signInThroughForm(page, OWNER, "/account");
    await expect(page).toHaveURL(/\/account$/);
    await expect(page.getByRole("heading", { level: 1, name: "Account" })).toBeVisible();
    const menu = page.getByRole("navigation", { name: "Account" });
    await expect(menu.getByRole("link", { name: "Example owner" })).toHaveAttribute(
      "href",
      "/account",
    );
    await expect(page.getByRole("navigation", { name: "Primary" })).toContainText("Businesses");
    await menu.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/sign-in$/);
    await page.goto("/account");
    await expect(page).toHaveURL(/\/sign-in\?next=%2Faccount$/);
  });

  test("tenant roles land on the businesses list and regulatory roles on the internal tools", async ({
    page,
  }) => {
    await signInThroughForm(page, OWNER);
    await expect(page).toHaveURL(/\/businesses$/);
    await expect(page.getByRole("heading", { level: 1, name: "Businesses" })).toBeVisible();
    await expect(page.getByText("GET /v1/businesses")).toBeVisible();
    await page.goto("/sign-in");
    await expect(page).toHaveURL(/\/businesses$/);
    await page.request.post("/sign-out");
    await signInThroughForm(page, ANALYST);
    await expect(page).toHaveURL(/\/admin$/);
    await expect(page.getByRole("heading", { level: 1, name: "Internal tools" })).toBeVisible();
  });

  test("the roles offered follow the tenant kind", async ({ page }) => {
    await page.goto("/sign-in");
    await page.getByLabel("Tenant kind").selectOption("internal");
    await expect(page.getByRole("checkbox", { name: "Analyst" })).toBeVisible();
    await expect(page.getByRole("checkbox", { name: "Owner" })).toHaveCount(0);
    await page.getByLabel("Tenant kind").selectOption("ca_firm");
    await expect(page.getByRole("checkbox", { name: "CA admin" })).toBeVisible();
  });

  test("sign-out is POST only and refuses another origin", async ({ page }) => {
    const get = await page.request.get("/sign-out", { maxRedirects: 0 });
    expect(get.status()).toBe(405);
    const foreign = await page.request.post("/sign-out", {
      headers: { origin: "https://evil.example" },
      maxRedirects: 0,
    });
    expect(foreign.status()).toBe(403);
    expect(foreign.headers()["content-type"]).toContain("application/problem+json");
    const own = await page.request.post("/sign-out", { maxRedirects: 0 });
    expect(own.status()).toBe(303);
    expect(own.headers()["location"]).toMatch(/\/sign-in$/);
    expect(own.headers()["set-cookie"]).toMatch(/cw_session=;/);
  });
});
