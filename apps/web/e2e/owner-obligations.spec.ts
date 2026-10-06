import { randomUUID } from "node:crypto";
import {
  createBusinessOnService,
  examplePan,
  newTenantPersona,
  seededBusinessId,
} from "./business-helpers";
import {
  ANALYST,
  IS_CI,
  expect,
  seededTenantId,
  signInThroughForm,
  test,
  type Persona,
} from "./fixtures";

/**
 * The obligation list, the calendar and one obligation's page against the services `make
 * web-stack` starts. That stack runs no worker, so no decision ever becomes an obligation here:
 * these specs cover the gates, the empty states, the filters and the window's limit, the grid's
 * keyboard and the not-found answers, with axe on each. The product project (e2e/product) walks
 * the same pages through real obligations.
 */
const NAME = "Example Duties Ltd";

test.describe("obligations", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait, make web-seed",
  );

  test("the list says why it is empty, keeps its filters in the address and refuses a window over the limit", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const business = await createBusinessOnService(persona.tenantId as string, {
      name: NAME,
      pan: examplePan(11),
    });
    await signInThroughForm(page, persona, `/b/${business.id}`);
    const tabs = page.getByRole("navigation", { name: "Pages of this business" });
    await tabs.getByRole("link", { name: "Obligations", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${business.id}/obligations$`));
    await expect(page.getByRole("heading", { level: 1, name: "Obligations" })).toBeVisible();
    await expect(tabs.getByRole("link", { name: "Obligations", exact: true })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await expect(page.getByRole("heading", { level: 2, name: "No obligations yet" })).toBeVisible();
    await expect(page.getByText(/at most 366 days, the obligation service's limit/)).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Not legal advice" })).toBeVisible();
    await checkA11y();

    const filters = page.getByRole("form", { name: "Filter the obligations" });
    await filters.getByLabel("Status").selectOption("todo");
    await filters.getByLabel("Due from").fill("2000-01-01");
    await filters.getByLabel("Due by").fill("2001-06-30");
    await filters.getByRole("button", { name: "Show" }).click();
    await expect(page).toHaveURL(/\?status=todo&from=2000-01-01&to=2001-06-30$/);
    await expect(
      page.getByText(
        "This window spans 547 days; the obligation service lists at most 366 at a time. Shorten it, or leave one end empty.",
      ),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { level: 2, name: "Nothing listed for this window" }),
    ).toBeVisible();
    await expect(page.getByLabel("Due by")).toHaveValue("2001-06-30");
    await checkA11y();

    await page.getByLabel("Due by").fill("2000-12-31");
    await page.getByRole("button", { name: "Show" }).click();
    await expect(page).toHaveURL(/to=2000-12-31$/);
    await expect(
      page.getByRole("heading", { level: 2, name: "No obligations match" }),
    ).toBeVisible();
    await expect(page.getByText(/Due from 1 Jan 2000 to 31 Dec 2000\./)).toBeVisible();
    await page.getByRole("link", { name: "Clear the filters" }).click();
    await expect(page).toHaveURL(new RegExp(`/b/${business.id}/obligations$`));
    await expect(page.getByRole("heading", { level: 2, name: "No obligations yet" })).toBeVisible();
  });

  test("the calendar is a grid the arrow keys move through, a month at a time", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const business = await createBusinessOnService(persona.tenantId as string, {
      name: NAME,
      pan: examplePan(12),
    });
    await signInThroughForm(page, persona, `/b/${business.id}/calendar?month=2000-02`);
    await expect(page.getByRole("heading", { level: 1, name: "Calendar" })).toBeVisible();
    const grid = page.getByRole("grid", { name: "February 2000" });
    await expect(grid).toBeVisible();
    await expect(page.getByText("Nothing falls due in February 2000.")).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "No day chosen" })).toBeVisible();
    await checkA11y();

    await grid.locator("[data-key='2000-02-10']").focus();
    await page.keyboard.press("ArrowRight");
    await expect(grid.locator("[data-key='2000-02-11']")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 2, name: "Due on 11 Feb 2000" })).toBeVisible();
    await expect(page.getByText("Nothing falls due on this day.")).toBeVisible();
    // Past the month's edge the grid asks the server for the next month.
    await page.keyboard.press("PageDown");
    await expect(page).toHaveURL(/\?month=2000-03$/);
    await expect(page.getByRole("grid", { name: "March 2000" })).toBeVisible();
    await expect(page.getByText("Nothing falls due in March 2000.")).toBeVisible();
    await expect(
      page.getByRole("grid", { name: "March 2000" }).locator("[data-key='2000-03-11']"),
    ).toBeFocused();
    await checkA11y();
    await page.getByRole("link", { name: "Previous month: February 2000" }).click();
    await expect(page).toHaveURL(/\?month=2000-02$/);
  });

  test("the onboarding summary looks for the first obligation and says so while it does", async ({
    page,
    checkA11y,
  }) => {
    const persona = newTenantPersona();
    const business = await createBusinessOnService(persona.tenantId as string, {
      name: NAME,
      pan: examplePan(13),
    });
    await signInThroughForm(page, persona, `/onboarding/${business.id}/done`);
    const first = page.locator("[data-slot='first-obligation']");
    await expect(
      first.getByRole("heading", { level: 2, name: "Your first obligation" }),
    ).toBeVisible();
    // The web stack has no worker: nothing becomes an obligation, so the page keeps looking.
    await expect(first.getByRole("status")).toContainText(
      "Working out what applies to this business",
    );
    await expect(first).toHaveAttribute("data-phase", "polling");
    await expect(first.getByRole("link", { name: "Open the obligations page" })).toHaveAttribute(
      "href",
      `/b/${business.id}/obligations`,
    );
    await checkA11y();
  });

  test("an unknown, a malformed or another tenant's obligation or business is not found", async ({
    page,
  }) => {
    const persona = newTenantPersona();
    const business = await createBusinessOnService(persona.tenantId as string, {
      name: NAME,
      pan: examplePan(14),
    });
    await signInThroughForm(page, persona);
    const seeded = seededBusinessId() as string;
    for (const path of [
      `/b/${business.id}/obligations/${randomUUID()}`,
      `/b/${business.id}/obligations/not-an-id`,
      `/b/${seeded}/obligations`,
      `/b/${seeded}/calendar`,
      `/b/${randomUUID()}/obligations`,
    ]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    }
  });

  test("every member reads them; an analyst is sent away and a visitor to sign in", async ({
    page,
  }) => {
    const owner = newTenantPersona();
    const business = await createBusinessOnService(owner.tenantId as string, {
      name: NAME,
      pan: examplePan(15),
    });
    const lead: Persona = {
      ...owner,
      key: `${owner.key}-lead`,
      roles: ["compliance_lead"],
      displayName: `${owner.displayName} lead`,
    };
    await signInThroughForm(page, lead, `/b/${business.id}/obligations`);
    await expect(page.getByRole("heading", { level: 1, name: "Obligations" })).toBeVisible();
    await page.context().clearCookies();
    await page.goto(`/b/${business.id}/calendar`);
    await expect(page).toHaveURL(/\/sign-in\?next=/);
    await signInThroughForm(page, ANALYST, `/b/${business.id}/obligations`);
    await expect(page).toHaveURL(/\/forbidden$/);
  });
});
