import { randomUUID } from "node:crypto";
import { createBusinessOnService, newTenantPersona } from "./business-helpers";
import { IS_CI, expect, seededTenantId, serviceUrl, signInThroughForm, test } from "./fixtures";

/**
 * Ask against the qa service `make web-stack` starts (the Playwright config turns
 * web.qa_enabled on). That stack has no obligations and no published rule, so the honest answer
 * there is usually that the question is not covered; the spec asks the service the same question
 * and compares the page with its answer rather than assuming one. The product project gets a
 * cited answer.
 */
const DEMO_GSTIN = "29ABCDE1234F1Z5";
const QUESTION = "What is due this month?";

interface AnswerBody {
  outcome: "answered" | "not_covered";
  answer: string;
  layer: string;
  citations: { quote: string }[];
}

test.describe("ask", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("a question about a registration gets the service's answer, honestly worded", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const tenantId = persona.tenantId as string;
    const business = await createBusinessOnService(tenantId, {
      name: "Example Questions Ltd",
      gstin: DEMO_GSTIN,
    });
    const registration = business.registrations[0];
    expect(registration).toBeDefined();
    await signInThroughForm(page, persona, `/b/${business.id}`);
    const tabs = page.getByRole("navigation", { name: "Pages of this business" });
    await tabs.getByRole("link", { name: "Ask", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${business.id}/ask$`));
    await expect(page.getByRole("heading", { level: 1, name: "Ask" })).toBeVisible();
    await checkA11y();

    const form = page.getByRole("form", { name: "Ask a question" });
    await form.getByRole("button", { name: "Ask" }).click();
    await expect(form.getByText("Write a question first.")).toBeVisible();
    await expect(form.getByLabel("About")).toHaveValue(registration?.id ?? "");

    await form.getByLabel(/Your question/).fill(QUESTION);
    await form.getByRole("button", { name: "Ask" }).click();
    const answer = page.locator("[data-slot='answer']");
    await expect(answer).toBeVisible({ timeout: 30_000 });

    const response = await fetch(`${serviceUrl("qa")}/v1/qa`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-tenant-id": tenantId },
      body: JSON.stringify({ question: QUESTION, business_node_id: registration?.id }),
    });
    expect(response.status).toBe(200);
    const expected = (await response.json()) as AnswerBody;
    await expect(answer).toHaveAttribute("data-outcome", expected.outcome);
    await expect(answer.locator("[data-slot='answer-text']")).toHaveText(expected.answer);
    await expect(answer).toContainText(
      expected.outcome === "answered" ? "Answered" : "Not covered",
    );
    await expect(answer.locator("[data-citation]")).toHaveCount(expected.citations.length);
    await expect(form.getByLabel(/Your question/)).toHaveValue(QUESTION);
    await expect(page.getByRole("complementary", { name: "Not legal advice" })).toBeVisible();
    await checkA11y();
  });

  test("another tenant's business and a malformed id are not found", async ({ page }) => {
    await signInThroughForm(page, newTenantPersona());
    for (const id of [randomUUID(), "not-an-id"]) {
      await page.goto(`/b/${id}/ask`);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });
});
