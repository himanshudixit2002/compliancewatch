import { ANALYST, IS_CI, OWNER, expect, seededTenantId, signInThroughForm, test } from "./fixtures";

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

  test("a refused submit keeps every value, the kind with its roles, and focuses the errors", async ({
    page,
  }) => {
    await page.goto("/sign-in");
    await page.getByLabel("Tenant kind").selectOption("internal");
    await page.getByLabel("Display name").fill("Example analyst");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText("Choose at least one role.")).toBeVisible();
    await expect(page.getByLabel("Tenant kind")).toHaveValue("internal");
    await expect(page.getByLabel("Display name")).toHaveValue("Example analyst");
    await expect(page.getByRole("checkbox", { name: "Analyst" })).not.toBeChecked();
    await expect(page.locator("[data-slot='sign-in-errors']")).toBeFocused();

    await page.getByRole("checkbox", { name: "Analyst" }).check();
    await page.getByLabel("Tenant id").fill("not-a-uuid");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByText("Enter a UUID, or leave it empty.")).toBeVisible();
    await expect(page.getByLabel("Tenant kind")).toHaveValue("internal");
    await expect(page.getByLabel("Display name")).toHaveValue("Example analyst");
    await expect(page.getByLabel("Tenant id")).toHaveValue("not-a-uuid");
    await expect(page.getByRole("checkbox", { name: "Analyst" })).toBeChecked();
    await expect(page.locator("[data-slot='sign-in-errors']")).toBeFocused();

    await page.getByLabel("Tenant id").fill("");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page).toHaveURL(/\/admin$/);
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

  // Needs `make web-stack && make web-stack-wait && make web-seed` first; the CI job runs them,
  // so there a missing seed state fails the test instead of skipping it.
  test("the last seeded tenant is offered and an owner signs into it", async ({
    page,
    checkA11y,
  }) => {
    const tenantId = seededTenantId();
    test.skip(tenantId === null && !IS_CI, "make web-seed has not run on this machine");
    if (tenantId === null) {
      throw new Error("no seed state (var/seed/last.json): the CI job runs make web-seed first");
    }
    await page.goto("/sign-in?next=%2Faccount");
    await page.getByRole("button", { name: "Use the last seeded tenant" }).click();
    await expect(page.getByLabel("Tenant id")).toHaveValue(tenantId);
    await checkA11y();
    await page.getByLabel("Tenant kind").selectOption(OWNER.tenantKind);
    await page.getByRole("checkbox", { name: "Owner" }).check();
    await page.getByLabel("Display name").fill(OWNER.displayName);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page).toHaveURL(/\/account$/);
    const facts = page.locator("dl[data-slot='key-value']");
    await expect(facts).toContainText(tenantId);
    await expect(facts).toContainText("Owner");
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
    expect(own.headers()["location"]).toBe("/sign-in");
    expect(own.headers()["set-cookie"]).toMatch(/cw_session=;/);
  });

  // next start builds the request URL from the address it binds (localhost), not from the
  // host the browser used; sign-out must still work, and stay, on any other host name.
  test("an owner signed in through 127.0.0.1 signs out and stays on that host", async ({
    browser,
    baseURL,
  }) => {
    const loopback = (baseURL ?? "").replace("//localhost", "//127.0.0.1");
    expect(loopback).toContain("127.0.0.1");
    const direct = await browser.newContext({ baseURL: loopback });
    try {
      const page = await direct.newPage();
      await page.goto("/account");
      await expect(page).toHaveURL(`${loopback}/sign-in?next=%2Faccount`);
      await signInThroughForm(page, OWNER, "/account");
      await expect(page).toHaveURL(`${loopback}/account`);
      const menu = page.getByRole("navigation", { name: "Account" });
      await menu.getByRole("button", { name: "Sign out" }).click();
      await expect(page).toHaveURL(`${loopback}/sign-in`);
      const cookies = await direct.cookies(loopback);
      expect(cookies.find((cookie) => cookie.name === "cw_session")).toBeUndefined();
      const scripted = await page.request.post("/sign-out", {
        headers: { origin: loopback },
        maxRedirects: 0,
      });
      expect(scripted.status()).toBe(303);
      expect(scripted.headers()["location"]).toBe("/sign-in");
    } finally {
      await direct.close();
    }
  });
});
