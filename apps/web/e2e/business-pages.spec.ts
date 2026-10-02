import { randomUUID } from "node:crypto";
import {
  createBusinessOnService,
  examplePan,
  newTenantPersona,
  readBusinessOnService,
} from "./business-helpers";
import { IS_CI, expect, seededTenantId, signInThroughForm, test } from "./fixtures";

/**
 * A business's pages against the real profile service, each test in a tenant of its own with a
 * business made on the service from the demo GSTIN (so the static lookup pre-fills it): the home,
 * the hierarchy with a new location, the attributes for a financial year with a changed answer,
 * the snapshot with the origin of each value, and the review tasks.
 */
const DEMO_GSTIN = "29ABCDE1234F1Z5";
const NAME = "Example Pages Ltd";
/** How the pages name the business as a node: its name with its PAN (the demo GSTIN's). */
const ENTITY = `${NAME} (PAN ABCDE1234F)`;

test.describe("business pages", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("the home, the hierarchy and a new location", async ({ page, checkA11y }) => {
    const persona = newTenantPersona();
    const business = await createBusinessOnService(persona.tenantId as string, {
      name: NAME,
      gstin: DEMO_GSTIN,
    });
    await signInThroughForm(page, persona);
    await page.goto("/businesses");
    await expect(page).toHaveURL(new RegExp(`/b/${business.id}$`));

    await expect(page.getByRole("heading", { level: 1, name: NAME })).toBeVisible();
    const tabs = page.getByRole("navigation", { name: "Pages of this business" });
    await expect(tabs.getByRole("link", { name: "Business" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByText(`${DEMO_GSTIN} (${NAME})`)).toBeVisible();
    await expect(page.getByRole("progressbar")).toHaveAttribute(
      "aria-valuetext",
      /\d+ of \d+ answered/,
    );
    await expect(page.getByRole("link", { name: "Continue the questions" })).toHaveAttribute(
      "href",
      `/onboarding/${business.id}/questions`,
    );
    const later = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Not available yet" }),
    });
    await expect(later.getByRole("link", { name: "Changes" })).toHaveAttribute(
      "href",
      `/b/${business.id}/changes`,
    );
    await checkA11y();

    await tabs.getByRole("link", { name: "Profile" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Profile" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText(NAME);
    await expect(page.getByRole("heading", { level: 3, name: DEMO_GSTIN })).toBeVisible();
    const form = page.getByRole("form", { name: `Add a location under ${DEMO_GSTIN}` });
    await form.getByRole("button", { name: "Add the location" }).click();
    await expect(form.getByText("Enter a label.")).toBeVisible();
    await expect(form.getByText("Enter a name.")).toBeVisible();
    await checkA11y();
    await form.getByRole("textbox", { name: /Label/ }).fill("EX-01");
    await form.getByRole("textbox", { name: /Name/ }).fill("Example branch");
    await form.getByRole("button", { name: "Add the location" }).click();
    await expect(form.getByText("Location EX-01 is added")).toBeVisible();
    await form.getByRole("textbox", { name: /Label/ }).fill("EX-01");
    await form.getByRole("textbox", { name: /Name/ }).fill("Example branch");
    await form.getByRole("button", { name: "Add the location" }).click();
    await expect(
      form.getByText("Location EX-01 was already under this registration"),
    ).toBeVisible();

    // The location's snapshot: everything it holds is inherited.
    await form.getByRole("link", { name: "Its snapshot" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Snapshot" })).toBeVisible();
    const nodes = page.getByRole("navigation", { name: "Business, registration or location" });
    await expect(nodes.getByRole("link")).toHaveCount(3);
    await expect(nodes.locator("[aria-current='page']")).toContainText("Example branch");
    const snapshot = page.getByRole("table", { name: /^Snapshot for \d{4}-\d{2}$/ });
    await expect(snapshot.getByText(`Inherited from ${ENTITY}`).first()).toBeVisible();
    await expect(snapshot.getByText("Stored on this node")).toHaveCount(0);
    await checkA11y();
  });

  test("attributes for a year: own and inherited, change an answer, other years", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const tenantId = persona.tenantId as string;
    const business = await createBusinessOnService(tenantId, { name: NAME, gstin: DEMO_GSTIN });
    await signInThroughForm(page, persona);
    await page.goto(`/b/${business.id}/attributes`);
    await expect(page.getByRole("heading", { level: 1, name: "Attributes" })).toBeVisible();
    const year = page.getByRole("combobox", { name: "Financial year" });
    const current = await year.inputValue();
    expect(current).toMatch(/^\d{4}-\d{2}$/);
    const own = page.getByRole("table", { name: `Values stored on ${ENTITY} for ${current}` });
    await expect(own).toContainText("GSTIN lookup");
    const unanswered = page.locator("section").filter({
      has: page.getByRole("heading", { name: "Not answered yet" }),
    });
    await expect(unanswered.getByRole("link", { name: "Answer Turnover band" })).toBeVisible();
    await checkA11y();

    // Answer a per-year attribute for this year.
    const before = (await readBusinessOnService(tenantId, business.id)).version as number;
    await unanswered.getByRole("link", { name: "Answer Turnover band" }).click();
    const edit = page.locator("[data-slot='attribute-edit']");
    await expect(
      edit.getByRole("heading", { name: `Change Turnover band on ${ENTITY}` }),
    ).toBeVisible();
    await expect(edit).toContainText(`The answer is for the financial year ${current}.`);
    await edit.getByRole("radio").first().click();
    await edit.getByRole("button", { name: "Save" }).click();
    await expect(edit.getByRole("status")).toHaveText(
      `Saved; the profile is now at version ${before + 1}.`,
    );
    await expect(own.locator("[data-attribute^='turnover_band']")).toContainText(current);
    await checkA11y();

    // Another year: the per-year answer is not there, and is asked for.
    const previous = `${Number(current.slice(0, 4)) - 1}-${current.slice(2, 4)}`;
    await year.selectOption(previous);
    await page.getByRole("button", { name: "Show" }).click();
    await expect(page).toHaveURL(new RegExp(`fy=${previous}`));
    await expect(
      page.getByRole("table", { name: `Values stored on ${ENTITY} for ${previous}` }),
    ).not.toContainText("Turnover band");
    await expect(unanswered.getByRole("link", { name: "Answer Turnover band" })).toBeVisible();

    // The registration inherits the business's values.
    const registration = business.registrations[0] as { id: string };
    await page
      .getByRole("navigation", { name: "Business, registration or location" })
      .getByRole("link", { name: new RegExp(DEMO_GSTIN) })
      .click();
    await expect(page).toHaveURL(new RegExp(`node=${registration.id}`));
    const inherited = page.getByRole("table", { name: new RegExp(`inherits for ${previous}$`) });
    await expect(inherited).toContainText(ENTITY);
    await checkA11y();

    // The snapshot for this year names where each value comes from.
    await page.goto(`/b/${business.id}/snapshot?node=${registration.id}&fy=${current}`);
    const snapshot = page.getByRole("table", { name: `Snapshot for ${current}` });
    await expect(snapshot.getByText("Stored on this node").first()).toBeVisible();
    await expect(snapshot.getByText(`Inherited from ${ENTITY}`).first()).toBeVisible();
    await expect(snapshot.locator("[data-attribute='turnover_band']")).toContainText(
      `Inherited from ${ENTITY}`,
    );
    await page.goto(`/b/${business.id}/snapshot?node=${registration.id}&fy=${previous}`);
    await expect(
      page
        .getByRole("table", { name: `Snapshot for ${previous}` })
        .locator("[data-attribute='turnover_band']"),
    ).toHaveCount(0);
    await checkA11y();

    // A compliance lead of the same tenant reads the values but changes none.
    await page.context().clearCookies();
    await signInThroughForm(page, {
      ...newTenantPersona("business", ["compliance_lead"]),
      tenantId,
    });
    await page.goto(`/b/${business.id}/attributes`);
    await expect(page.getByRole("heading", { level: 1, name: "Attributes" })).toBeVisible();
    await expect(page.getByRole("link", { name: /^Change / })).toHaveCount(0);
    await expect(page.getByRole("link", { name: /^Answer / })).toHaveCount(0);
  });

  test("review tasks, and a business that is not the tenant's", async ({ page, checkA11y }) => {
    const persona = newTenantPersona();
    const tenantId = persona.tenantId as string;
    // A GSTIN the static lookup does not know opens a verify_registration task.
    const business = await createBusinessOnService(tenantId, {
      name: NAME,
      gstin: "27ABCDE1234F1Z5",
    });
    const other = await createBusinessOnService(newTenantPersona().tenantId as string, {
      name: "Example Other Tenant",
      pan: examplePan(1),
    });
    await signInThroughForm(page, persona);
    await page.goto(`/b/${business.id}/review-tasks`);
    await expect(page.getByRole("heading", { level: 1, name: "Review tasks" })).toBeVisible();
    await expect(page.getByText("1 open of 1.")).toBeVisible();
    const table = page.getByRole("table", { name: "Review tasks on this business" });
    await expect(table).toContainText("GSTIN details not verified by a lookup provider");
    await expect(table).toContainText("Open");
    await checkA11y();

    for (const path of [`/b/${other.id}`, `/b/${randomUUID()}/attributes`, "/b/not-an-id"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
    // A node of another tenant's business is not shown under this one.
    await page.goto(`/b/${business.id}/snapshot?node=${other.id}`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  });
});
