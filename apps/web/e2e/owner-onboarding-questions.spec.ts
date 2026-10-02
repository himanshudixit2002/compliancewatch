import { randomUUID } from "node:crypto";
import type { Page } from "@playwright/test";
import {
  newTenantPersona,
  readBusinessOnService,
  reviewTasksOnService,
  signInWithConsents,
} from "./business-helpers";
import { IS_CI, expect, seededTenantId, signInThroughForm, test } from "./fixtures";

/**
 * The questions step and the summary against the real profile service: a new owner adds the demo
 * business, then answers the checklist one question at a time with Save, Not sure and Does not
 * apply. The wording comes from the service's ontology, so the spec reads the questions from the
 * page rather than naming them.
 */
const PROGRESS = /(\d+) of (\d+) answered/;

async function answered(page: Page): Promise<number> {
  const text = await page.getByRole("progressbar").getAttribute("aria-valuetext");
  const match = PROGRESS.exec(text ?? "");
  expect(match, `progress text: ${text}`).not.toBeNull();
  return Number((match as RegExpExecArray)[1]);
}

async function heading(page: Page): Promise<string> {
  const text = await page.getByRole("heading", { level: 1 }).textContent();
  expect(text?.trim().length).toBeGreaterThan(0);
  return (text as string).trim();
}

/** Waits for the page the answer moved to, and returns the question it asks. */
async function nextQuestion(page: Page, previous: string): Promise<string> {
  await expect(page.getByRole("heading", { level: 1 })).not.toHaveText(previous);
  return heading(page);
}

test.describe("onboarding: questions and summary", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("answers one question at a time, moves past Not sure and ends on the summary", async ({
    page,
    checkA11y,
  }) => {
    test.setTimeout(90_000);
    const persona = newTenantPersona();
    await signInWithConsents(page, persona);
    await page.getByRole("textbox", { name: /GSTIN/ }).fill("29ABCDE1234F1Z5");
    await page.getByRole("textbox", { name: /Business name/ }).fill("Example Questions Ltd");
    await page.getByRole("button", { name: "Add the business" }).click();
    await page.getByRole("link", { name: "Continue to the questions" }).click();
    await expect(page).toHaveURL(/\/onboarding\/[0-9a-f-]{36}\/questions$/);
    const businessId = new URL(page.url()).pathname.split("/")[2] as string;

    await expect(
      page.getByRole("navigation", { name: "Onboarding steps" }).locator("[aria-current='step']"),
    ).toContainText("Questions");
    const start = await answered(page);
    expect(start).toBeGreaterThan(0); // the GSTIN lookup pre-filled some
    const form = page.locator("[data-slot='answer-form']");
    const first = await heading(page);
    await checkA11y();

    // Not sure: stored, not counted, and not asked again in this run.
    await form.getByRole("button", { name: "Not sure" }).click();
    let current = await nextQuestion(page, first);
    await expect(page).toHaveURL(/\?saved=[a-z_]+$/);
    await expect(
      page.getByRole("status").filter({ hasText: "Saved your answer about" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
    await expect(page.getByText(/You answered Not sure to 1 of the questions/)).toBeVisible();
    expect(await answered(page)).toBe(start);
    const asked = new Set([first, current]);

    // A per-year question names its year; Save with the first option counts.
    await expect(
      page.getByText(/The answer is for the financial year \d{4}-\d{2}\./),
    ).toBeVisible();
    await form.getByRole("radio").first().click();
    await form.getByRole("button", { name: "Save" }).click();
    current = await nextQuestion(page, current);
    asked.add(current);
    expect(await answered(page)).toBe(start + 1);

    // Does not apply counts and opens a review task, listed under the form.
    await form.getByRole("button", { name: "Does not apply" }).click();
    current = await nextQuestion(page, current);
    asked.add(current);
    expect(await answered(page)).toBe(start + 2);
    await expect(page.getByText(/It opened a review task an analyst will look at/)).toBeVisible();
    const tasks = page.getByRole("table", { name: "Open review tasks on this business" });
    await expect(tasks).toContainText("You said this does not apply; an analyst will confirm");
    await checkA11y();

    // A whole number: a malformed one is refused under the control, then a good one is stored.
    const count = form.getByRole("textbox");
    await count.fill("twelve");
    await form.getByRole("button", { name: "Save" }).click();
    await expect(form.getByText("Enter a whole number, such as 12.")).toBeVisible();
    await expect(page.locator("[data-slot='answer-errors']")).toBeFocused();
    await checkA11y();
    await form.getByRole("textbox").fill("12");
    await form.getByRole("button", { name: "Save" }).click();
    current = await nextQuestion(page, current);
    asked.add(current);
    expect(await answered(page)).toBe(start + 3);

    // The rest Not sure: each question is new, and the last one leads to the summary.
    let unsure = 1;
    for (let guard = 0; guard < 30 && !page.url().endsWith("/done"); guard += 1) {
      const before = current;
      await form.getByRole("button", { name: "Not sure" }).click();
      unsure += 1;
      await page.waitForURL((url) => url.pathname.endsWith("/done") || url.search !== "");
      await expect(page.getByRole("heading", { level: 1 })).not.toHaveText(before);
      if (page.url().endsWith("/done")) break;
      current = await heading(page);
      expect(asked.has(current), `asked again: ${current}`).toBe(false);
      asked.add(current);
    }
    await expect(page).toHaveURL(new RegExp(`/onboarding/${businessId}/done$`));

    await expect(page.getByRole("heading", { level: 1, name: "Onboarding summary" })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Onboarding steps" }).locator("[aria-current='step']"),
    ).toContainText("Done");
    await expect(page.getByText("Example Questions Ltd, PAN ABCDE1234F")).toBeVisible();
    const unsureList = page
      .locator("section")
      .filter({ has: page.getByRole("heading", { name: "Answered Not sure" }) })
      .getByRole("listitem");
    await expect(unsureList).toHaveCount(unsure);
    await expect(page.getByRole("heading", { name: "Not answered yet" })).toHaveCount(0);
    await expect(
      page.getByRole("table", { name: "Open review tasks on this business" }),
    ).toContainText("You said this does not apply; an analyst will confirm");
    await expect(page.getByRole("link", { name: "Open the business" })).toHaveAttribute(
      "href",
      `/b/${businessId}`,
    );
    await checkA11y();

    // The service holds the not-applicable task on the entity or the registration.
    const tenantId = persona.tenantId as string;
    const business = await readBusinessOnService(tenantId, businessId);
    const nodeIds = [
      businessId,
      ...(business.registrations as { id: string }[]).map((node) => node.id),
    ];
    const reasons = (await Promise.all(nodeIds.map((id) => reviewTasksOnService(tenantId, id))))
      .flat()
      .filter((task) => task.open)
      .map((task) => task.reason);
    expect(reasons).toContain("not_applicable");

    // Asking the unsure ones again starts from the first of them.
    await page.getByRole("button", { name: "Answer these now" }).click();
    await expect(page).toHaveURL(new RegExp(`/onboarding/${businessId}/questions$`));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(first);
    await expect(page.getByText(/You answered Not sure to this before/)).toBeVisible();
  });

  test("an unknown business is not found and a compliance lead is sent to the forbidden page", async ({
    page,
  }) => {
    // The page streams behind its loading state, so a missing business is Next's streamed
    // not-found page: status 200 with the not-found UI and a noindex robots tag.
    await signInThroughForm(page, newTenantPersona());
    for (const path of [`/onboarding/${randomUUID()}/questions`, "/onboarding/not-an-id/done"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
      await expect(page.locator('meta[name="robots"]').first()).toHaveAttribute(
        "content",
        /noindex/,
      );
    }

    await page.context().clearCookies();
    await signInThroughForm(page, newTenantPersona("business", ["compliance_lead"]));
    await page.goto(`/onboarding/${randomUUID()}/questions`);
    await expect(page).toHaveURL(/\/forbidden$/);
  });
});
