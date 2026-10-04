import {
  ANALYST,
  IS_CI,
  OWNER,
  expect,
  seededTenantId,
  serviceUrl,
  test,
  waitForHydration,
} from "./fixtures";
import { RECORDED_DOCUMENT } from "./rulebook-helpers";

/**
 * The clause search against the rulebook the stack runs, over the recorded notification `make
 * web-seed` registers. The words are posted: the address never changes. Read-only.
 */
const TOOL = "/admin/rulebook/search";
const WORDS = "furnishing the return";

interface Hit {
  clause_id: string;
  clause_ref: string;
  document_id: string;
  lexical_rank: number | null;
  vector_rank: number | null;
}

async function searchOnService(text: string): Promise<Hit[]> {
  const response = await fetch(`${serviceUrl("rulebook")}/v1/rulebook/search`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text, k: 8 }),
  });
  expect(response.status).toBe(200);
  return (await response.json()) as Hit[];
}

test.describe("clause search", () => {
  test("a tenant role gets a 404", async ({ page, signIn }) => {
    await signIn(OWNER);
    expect((await page.goto(TOOL))?.status()).toBe(404);
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
    );

    test.beforeEach(async ({ signIn }) => {
      await signIn(ANALYST);
    });

    test("finds the recorded clause with its ranks and the words marked, without changing the address", async ({
      page,
      checkA11y,
    }) => {
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Clause search" }).click();
      await expect(page).toHaveURL(new RegExp(`${TOOL}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Clause search" })).toBeVisible();
      await checkA11y();
      expect(RECORDED_DOCUMENT.textOf("en.p3")).toContain("furnishing the return");
      const expected = await searchOnService(WORDS);
      const recorded = expected.find(
        (hit) => hit.document_id === RECORDED_DOCUMENT.documentId && hit.clause_ref === "en.p3",
      );
      if (recorded === undefined) throw new Error("the rulebook does not find the recorded clause");

      await waitForHydration(page, "[data-slot='clause-search'] textarea");
      await page.getByLabel(/^Words/).fill(WORDS);
      await page.getByRole("button", { name: "Search" }).click();
      await expect(page.locator("[data-slot='search-summary']")).toHaveText(
        `${expected.length} clauses found`,
      );
      await expect(page).toHaveURL(new RegExp(`${TOOL}$`));
      const hit = page.locator(`[data-slot='search-hit'][data-clause='${recorded.clause_id}']`);
      await expect(hit).toContainText(`Clause en.p3 of ${RECORDED_DOCUMENT.external_ref}`);
      await expect(hit.locator("[data-rank='lexical']")).toHaveText(
        String(recorded.lexical_rank ?? "Not found by this search"),
      );
      await expect(hit.locator("[data-rank='vector']")).toHaveText(
        recorded.vector_rank === null ? "Not found by this search" : String(recorded.vector_rank),
      );
      await expect(hit.locator("mark").first()).toHaveText(/^furnish/i);
      await expect(
        hit
          .locator("mark")
          .filter({ hasText: /^return$/i })
          .first(),
      ).toBeVisible();
      await expect(page.getByLabel(/^Words/)).toHaveValue(WORDS);
      await checkA11y();

      await hit.getByRole("link", { name: "Open clause en.p3 in its document" }).click();
      await expect(page).toHaveURL(
        new RegExp(
          `/admin/rulebook/documents/${RECORDED_DOCUMENT.documentId}\\?clause_id=${recorded.clause_id}$`,
        ),
      );
      await expect(page.locator("[id='clause-en.p3']")).toHaveAttribute("data-marked", "clause");
    });

    test("says when nothing matched, and asks for the words", async ({ page, checkA11y }) => {
      const nothing = "zzzexample qqqexample";
      expect(await searchOnService(nothing)).toEqual([]);
      await page.goto(TOOL);
      await waitForHydration(page, "[data-slot='clause-search'] textarea");
      await page.getByRole("button", { name: "Search" }).click();
      await expect(page.getByText("Enter the words to search for.")).toBeVisible();
      await expect(page.getByLabel(/^Words/)).toBeFocused();
      await page.getByLabel(/^Words/).fill(nothing);
      await page.getByRole("button", { name: "Search" }).click();
      await expect(page.getByRole("heading", { name: "No clause matched" })).toBeVisible();
      await checkA11y();
    });
  });
});
