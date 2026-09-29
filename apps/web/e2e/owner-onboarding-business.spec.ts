import {
  newTenantPersona,
  readBusinessOnService,
  reviewTasksOnService,
  signInWithConsents,
} from "./business-helpers";
import { IS_CI, expect, seededTenantId, signInThroughForm, test } from "./fixtures";

/**
 * The business step against the real identity and profile services (make web-stack, which runs
 * the profile service with its built-in static GSTIN lookup). Each test signs in to a new tenant
 * so the business it adds is the tenant's only one.
 */
const DEMO_GSTIN = "29ABCDE1234F1Z5";
/** A well-formed GSTIN the static lookup does not know. */
const UNKNOWN_GSTIN = "27ABCDE1234F1Z5";

test.describe("onboarding: business step", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("asks for the consents before a business can be added", async ({ page, checkA11y }) => {
    await signInThroughForm(page, newTenantPersona(), "/onboarding/business");
    await expect(page.getByRole("heading", { level: 1, name: "Add a business" })).toBeVisible();
    await expect(page.getByText("Agree to the terms first")).toBeVisible();
    await expect(page.getByRole("textbox", { name: /GSTIN/ })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Go to the consent step" })).toHaveAttribute(
      "href",
      "/onboarding",
    );
    await checkA11y();
  });

  test("adds a business from the demo GSTIN and shows what the lookup returned", async ({
    page,
    checkA11y,
  }) => {
    await signInWithConsents(page, newTenantPersona());
    await expect(
      page.getByRole("navigation", { name: "Onboarding steps" }).locator("[aria-current='step']"),
    ).toContainText("Business");
    await expect(page.getByText(/knows only the demo GSTIN 29ABCDE1234F1Z5/)).toBeVisible();
    await checkA11y();

    // Nothing typed: each required field says so.
    await page.getByRole("button", { name: "Add the business" }).click();
    await expect(page.getByText("Enter the GSTIN.", { exact: true })).toBeVisible();
    await expect(page.getByText("Enter the name the business goes by.")).toBeVisible();
    await expect(page.locator("[data-slot='business-errors']")).toBeFocused();
    await checkA11y();

    await page.getByRole("textbox", { name: /GSTIN/ }).fill("29abcde 1234f1z5");
    await page.getByRole("textbox", { name: /Business name/ }).fill("Example Traders");
    await page.getByRole("button", { name: "Add the business" }).click();

    const heading = page.getByRole("heading", { level: 2, name: "Example Traders is added" });
    await expect(heading).toBeFocused();
    const panel = page.locator("[data-slot='prefill-panel']");
    await expect(panel).toContainText(DEMO_GSTIN);
    await expect(panel).toContainText("ABCDE1234F");
    await expect(
      page.getByRole("heading", { level: 3, name: "What the GSTIN lookup returned" }),
    ).toBeVisible();
    // The static lookup's own demo entry, as the service returned it.
    await expect(panel).toContainText("Legal name");
    await expect(panel).toContainText("Registered since");
    await expect(panel).toContainText("Stored on the profile from the GSTIN:");
    await expect(panel).toContainText(/\d+ of \d+ answered/);
    await checkA11y();

    const next = page.getByRole("link", { name: "Continue to the questions" });
    const href = await next.getAttribute("href");
    expect(href).toMatch(/^\/onboarding\/[0-9a-f-]{36}\/questions$/);

    // The same GSTIN again, from a fresh form: the business is already on file.
    await page.getByRole("link", { name: "Add another business" }).click();
    await page.getByRole("textbox", { name: /GSTIN/ }).fill(DEMO_GSTIN);
    await page.getByRole("textbox", { name: /Business name/ }).fill("Example Traders");
    await page.getByRole("button", { name: "Add the business" }).click();
    await expect(
      page.getByRole("heading", { name: "Example Traders was already in your account" }),
    ).toBeVisible();
    await expect(page.getByRole("link", { name: "Continue to the questions" })).toHaveAttribute(
      "href",
      href as string,
    );
  });

  test("says plainly when the lookup knows nothing and names the review task", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    await signInWithConsents(page, persona);
    await page.getByRole("textbox", { name: /GSTIN/ }).fill(UNKNOWN_GSTIN);
    await page.getByRole("textbox", { name: /Business name/ }).fill("Example Works");
    await page.getByRole("textbox", { name: /Registration name/ }).fill("Example branch");
    await page.getByRole("button", { name: "Add the business" }).click();

    const manual = page.locator("[data-slot='prefill-manual']");
    await expect(manual).toContainText("No lookup details for this GSTIN");
    await expect(manual).toContainText("A review task was opened");
    await expect(page.getByText("What the GSTIN lookup returned")).toHaveCount(0);
    await checkA11y();

    // The service holds the business with the named registration and the open task.
    const href = await page
      .getByRole("link", { name: "Continue to the questions" })
      .getAttribute("href");
    const businessId = (href as string).split("/")[2] as string;
    const business = await readBusinessOnService(persona.tenantId as string, businessId);
    const registrations = business.registrations as { id: string; key: string; name: string }[];
    expect(registrations.map((node) => [node.key, node.name])).toEqual([
      [UNKNOWN_GSTIN, "Example branch"],
    ]);
    const tasks = await reviewTasksOnService(
      persona.tenantId as string,
      (registrations[0] as { id: string }).id,
    );
    expect(tasks.filter((task) => task.open).map((task) => task.reason)).toContain(
      "verify_registration",
    );
  });
});
