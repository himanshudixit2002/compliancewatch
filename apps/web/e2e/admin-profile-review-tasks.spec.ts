import { randomUUID } from "node:crypto";
import { ANALYST, IS_CI, OWNER, expect, seededState, serviceUrl, test } from "./fixtures";

/**
 * The profile review task lookup against the profile service, with the tenant and the nodes
 * `make web-seed` recorded: the registration's facts, open tasks and snapshot compared with the
 * service's answers for that tenant, the way up to its business, and the answers for a node the
 * tenant does not hold. It only reads, so it runs in parallel and again on the same stack.
 */
const PAGE = "/admin/profiles/review-tasks";

async function profileGet<T>(path: string, tenant: string): Promise<T> {
  const response = await fetch(`${serviceUrl("profile")}${path}`, {
    headers: { "x-tenant-id": tenant },
  });
  expect(response.status, `GET ${path} on the profile service`).toBe(200);
  return (await response.json()) as T;
}

test.describe("profile review tasks", () => {
  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto(PAGE))?.status()).toBe(404);
  });

  test("a malformed lookup is refused on its fields, with what was typed kept", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    await signIn(ANALYST);
    await page.goto(`${PAGE}?tenant=not-a-tenant&node=&fy=2000`);
    await expect(page.getByText("This is not a tenant id (a UUID).")).toBeVisible();
    await expect(page.getByText("Give the year as 2026-27.")).toBeVisible();
    await expect(page.getByLabel(/^Tenant id/)).toHaveValue("not-a-tenant");
    await checkA11y();
  });

  test.describe("against the stack", () => {
    const state = seededState();
    test.skip(
      !IS_CI && state === null,
      "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
    );

    test("looks up the seeded registration: its facts, open tasks and snapshot", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const tenant = state?.tenant_id as string;
      const registration = state?.registration_node_id as string;
      const entity = state?.entity_node_id as string;
      await signIn(ANALYST);
      await page.goto("/admin");
      await page
        .locator("aside")
        .getByRole("link", { name: "Profile review tasks", exact: true })
        .click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
      const fy = await page.getByLabel(/^Financial year/).inputValue();
      await page.getByLabel(/^Tenant id/).fill(tenant);
      await page.getByLabel(/^Node id/).fill(registration);
      await page.getByRole("button", { name: "Look up" }).click();
      await expect(page).toHaveURL(new RegExp(`tenant=${tenant}&node=${registration}&fy=${fy}$`));

      const node = await profileGet<{ key: string; name: string }>(
        `/v1/profile/nodes/${registration}`,
        tenant,
      );
      const facts = page.locator("[data-slot='node-facts']");
      await expect(facts).toContainText(node.key);
      await expect(facts).toContainText("Registration");
      const tasks = await profileGet<{ id: string }[]>(
        `/v1/profile/nodes/${registration}/review-tasks`,
        tenant,
      );
      if (tasks.length === 0) {
        await expect(
          page.getByRole("heading", { name: "No review task is open on this node" }),
        ).toBeVisible();
      } else {
        await expect(page.locator("tr[data-task]")).toHaveCount(tasks.length);
      }
      const snapshot = await profileGet<{ attributes: Record<string, unknown> }>(
        `/v1/profile/nodes/${registration}/snapshot?fy=${fy}`,
        tenant,
      );
      await expect(page.locator("tr[data-attribute]")).toHaveCount(
        Object.keys(snapshot.attributes).length,
      );
      await checkA11y();

      await facts.getByRole("link", { name: entity }).click();
      await expect(page).toHaveURL(new RegExp(`node=${entity}`));
      await expect(page.locator("[data-slot='node-facts']")).toContainText("Legal entity");
    });

    test("says when the tenant holds no node with the id", async ({ page, signIn }) => {
      await signIn(ANALYST);
      await page.goto(`${PAGE}?tenant=${state?.tenant_id as string}&node=${randomUUID()}`);
      await expect(
        page.getByRole("heading", { name: "No node with this id in this tenant" }),
      ).toBeVisible();
    });
  });
});
