import { formatDecimalRupees } from "../src/shared/lib/money.ts";
import { ANALYST, IS_CI, OWNER, expect, seededTenantId, serviceUrl, test } from "./fixtures";

/**
 * The LLM gateway's pages against the gateway the stack runs: the prompts and the model routes
 * as the gateway lists them, and the spend against its monthly budgets, each compared with the
 * gateway's own answer. They only read, so they run in parallel and again on the same stack.
 */
async function gatewayGet<T>(path: string): Promise<T> {
  const response = await fetch(`${serviceUrl("llm-gateway")}${path}`);
  expect(response.status, `GET ${path} on the gateway`).toBe(200);
  return (await response.json()) as T;
}

interface Usage {
  key: string;
  spent_inr: string;
  budget_inr: string;
  month: string;
}

const FEATURES = ["extraction", "judgement", "qa", "classification", "smoke", "retrieval"];

test.describe("LLM gateway pages", () => {
  test("a tenant role gets a 404 for each", async ({ page, signIn }) => {
    await signIn(OWNER);
    for (const path of ["/admin/llm/prompts", "/admin/llm/models", "/admin/llm/usage"]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services: make web-stack, make web-stack-wait and make web-seed",
    );

    test.beforeEach(async ({ signIn }) => {
      await signIn(ANALYST);
    });

    test("lists the prompts the gateway serves and what edits wait for", async ({
      page,
      checkA11y,
    }) => {
      const prompts =
        await gatewayGet<{ name: string; version: string; eval_cases: number }[]>(
          "/v1/llm-gateway/prompts",
        );
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Prompts", exact: true }).click();
      await expect(page).toHaveURL(/\/admin\/llm\/prompts$/);
      await expect(page.getByRole("heading", { level: 1, name: "Prompts" })).toBeVisible();
      await expect(page.locator("tr[data-prompt]")).toHaveCount(prompts.length);
      for (const prompt of prompts) {
        const row = page.locator(`tr[data-prompt='${prompt.name}@${prompt.version}']`);
        await expect(row).toBeVisible();
        await expect(row).toContainText(
          prompt.eval_cases === 0 ? "No eval case" : String(prompt.eval_cases),
        );
      }
      await expect(page.locator("[data-slot='edit-awaits']")).toContainText(
        "PUT /v1/llm-gateway/prompts/{name}",
      );
      await checkA11y();
    });

    test("shows each feature's model route as the gateway applies it", async ({
      page,
      checkA11y,
    }) => {
      const routes =
        await gatewayGet<{ feature: string; primary: string; source: string }[]>(
          "/v1/llm-gateway/models",
        );
      await page.goto("/admin/llm/models");
      await expect(page.getByRole("heading", { level: 1, name: "Model routes" })).toBeVisible();
      await expect(page.locator("tr[data-feature]")).toHaveCount(routes.length);
      for (const route of routes) {
        const row = page.locator(`tr[data-feature='${route.feature}']`);
        await expect(row).toContainText(route.primary);
        await expect(row).toContainText(
          route.source === "override" ? "Set by the gateway's environment" : "Default",
        );
      }
      await checkA11y();
    });

    test("shows every feature's budget for the month, then one tenant's", async ({
      page,
      checkA11y,
    }) => {
      await page.goto("/admin/llm/usage");
      await expect(
        page.getByRole("heading", { level: 1, name: "Usage and budgets" }),
      ).toBeVisible();
      const month = await page.getByLabel(/^Month/).inputValue();
      expect(month).toMatch(/^2\d{3}-\d{2}$/);
      // Budgets are compared exactly; spend only by its shape, since other specs ask questions
      // that the gateway counts while this one reads.
      for (const feature of FEATURES) {
        const usage = await gatewayGet<Usage>(
          `/v1/llm-gateway/usage?feature=${feature}&month=${month}`,
        );
        const card = page.locator(`[data-usage='feature:${feature}']`);
        await expect(card).toContainText(formatDecimalRupees(usage.budget_inr));
        await expect(card).toContainText(/Spent\s*Rs [\d,]+\.\d{2,}/);
      }
      await checkA11y();

      const tenant = seededTenantId() as string;
      await page.getByLabel(/^Tenant id/).fill(tenant);
      await page.getByRole("button", { name: "Show spend" }).click();
      await expect(page).toHaveURL(new RegExp(`tenant=${tenant}`));
      const usage = await gatewayGet<Usage>(
        `/v1/llm-gateway/usage?tenant_id=${tenant}&month=${month}`,
      );
      const card = page.locator(`[data-usage='tenant:${tenant}']`);
      await expect(card).toContainText(formatDecimalRupees(usage.budget_inr));
      await expect(page.locator("[data-usage]")).toHaveCount(1);

      await page.getByLabel(/^Month/).fill("2000-13");
      await page.getByRole("button", { name: "Show spend" }).click();
      await expect(page.getByText("Give the month as YYYY-MM, such as 2000-01.")).toBeVisible();
      await expect(page.locator("[data-usage]")).toHaveCount(0);
      await checkA11y();
    });
  });
});
