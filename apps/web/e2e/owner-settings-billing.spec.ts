import { newTenantPersona } from "./business-helpers";
import { IS_CI, expect, seededTenantId, serviceUrl, signInThroughForm, test } from "./fixtures";

/**
 * The billing page against the real identity service (make web-stack, then make web-seed; each
 * test in a tenant of its own). make web-stack starts identity with no billing provider unless
 * it was given BILLING=memory, and make web-e2e passes the same choice as WEB_STACK_BILLING, so
 * the subscribe test expects the state the stack is in: "billing is not connected" (the 503
 * billing-disabled) by default, a started in-memory subscription with BILLING=memory.
 */
const BILLING = process.env.WEB_STACK_BILLING?.trim() || "none";

interface ServicePlan {
  key: string;
  name: string;
  description: string;
}

async function servicePlans(): Promise<ServicePlan[]> {
  const response = await fetch(`${serviceUrl("identity")}/v1/identity/billing/plans`);
  expect(response.status).toBe(200);
  return (await response.json()) as ServicePlan[];
}

test.describe("settings: billing", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("an owner sees the service's plans and starts a subscription", async ({
    page,
    checkA11y,
  }) => {
    await signInThroughForm(page, newTenantPersona(), "/settings/billing");
    await expect(page.getByRole("heading", { level: 1, name: "Billing" })).toBeVisible();
    const plans = await servicePlans();
    expect(plans.length).toBeGreaterThan(0);
    for (const plan of plans) {
      const card = page.locator(`[data-plan='${plan.key}']`);
      await expect(card).toContainText(plan.name);
      await expect(card).toContainText(plan.description);
    }
    await checkA11y();

    const form = page.getByRole("form", { name: "Start a subscription" });
    await form.getByRole("button", { name: "Start the subscription" }).click();
    await expect(form).toContainText("Enter the billing email.");
    await expect(form).toContainText("Enter the billing name.");

    await form.getByLabel("Billing email").fill("owner@example.com");
    await form.getByLabel("Billing name").fill("Example Traders");
    await form.getByRole("button", { name: "Start the subscription" }).click();
    const result = page.locator("[data-slot='subscribe-result']");
    if (BILLING === "memory") {
      await expect(result.locator("[data-slot='subscription']")).toContainText(
        "Subscription started",
      );
      await expect(result).toContainText("Created");
      await expect(result).toContainText("The provider returned no checkout page.");
    } else {
      const disabled = result.locator("[data-slot='billing-disabled']");
      await expect(disabled).toContainText("Billing is not connected yet");
      await expect(disabled).toContainText("nothing was charged");
      await expect(disabled.locator("code")).toHaveText(/^[0-9a-f-]{36}$/);
      await expect(result).toBeFocused();
      // What was sent stays in the form.
      await expect(form.getByLabel("Billing email")).toHaveValue("owner@example.com");
    }
    await checkA11y();
  });

  test("a CA admin sees the same plans", async ({ page }) => {
    await signInThroughForm(page, newTenantPersona("ca_firm", ["ca_admin"]), "/settings/billing");
    await expect(page.getByRole("heading", { level: 1, name: "Billing" })).toBeVisible();
    for (const plan of await servicePlans()) {
      await expect(page.locator(`[data-plan='${plan.key}']`)).toContainText(plan.name);
    }
  });

  test("a staff member is sent to the forbidden page", async ({ page }) => {
    await signInThroughForm(page, newTenantPersona("business", ["staff"]), "/settings/billing");
    await expect(page).toHaveURL(/\/forbidden$/);
  });
});
