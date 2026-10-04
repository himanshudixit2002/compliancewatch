import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
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

/**
 * The documents tool against the recorded notification `make web-seed` registers. Everything
 * here only reads that document, so the specs can run in parallel and again on the same stack.
 */
interface RecordedDocument {
  sha256: string;
  title: string;
  external_ref: string;
  clauses: { clause_ref: string; text: string }[];
}

interface RecordedMentions {
  mentions: { clause_ref: string; text: string; span_start: number; span_end: number }[];
}

const FIXTURES = resolve(__dirname, "../scripts/seed/fixtures/rulebook");
const RECORDED = JSON.parse(
  readFileSync(resolve(FIXTURES, "gst-ct-01-2026.document.json"), "utf8"),
) as RecordedDocument;
const MENTIONS = JSON.parse(
  readFileSync(resolve(FIXTURES, "gst-ct-01-2026.mentions.json"), "utf8"),
) as RecordedMentions;

/** The rulebook's id for a document: the first 32 hex characters of its sha256, as a UUID. */
const hex = RECORDED.sha256.slice(0, 32);
const DOCUMENT_ID = `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
const VIEWER = `/admin/rulebook/documents/${DOCUMENT_ID}`;

/** The clause ids the rulebook gave the recorded clauses, read from the service. */
async function clauseIds(): Promise<Record<string, string>> {
  const response = await fetch(`${serviceUrl("rulebook")}/v1/rulebook/documents/${DOCUMENT_ID}`);
  expect(response.status, "the seeded document (make web-seed)").toBe(200);
  const body = (await response.json()) as { clauses: { clause_id: string; clause_ref: string }[] };
  return Object.fromEntries(body.clauses.map((clause) => [clause.clause_ref, clause.clause_id]));
}

test.describe("rulebook documents", () => {
  test("a tenant role gets a 404 for the tool and the viewer", async ({ page, signIn }) => {
    await signIn(OWNER);
    for (const path of ["/admin/rulebook/documents", VIEWER]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test("a malformed id is a real 404 inside the admin shell", async ({ page, signIn }) => {
    await signIn(ANALYST);
    const response = await page.goto("/admin/rulebook/documents/not-a-document");
    expect(response?.status()).toBe(404);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to the internal tools" })).toBeVisible();
  });

  test.describe("against the seeded document", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
    );

    test.beforeEach(async ({ signIn }) => {
      await signIn(ANALYST);
    });

    test("opens the document from its sha256 and shows every clause with its page", async ({
      page,
      checkA11y,
    }) => {
      await page.goto("/admin/rulebook/documents");
      await expect(page.getByRole("heading", { level: 1, name: "Documents" })).toBeVisible();
      await expect(page.locator("aside").getByRole("link", { name: "Documents" })).toHaveAttribute(
        "aria-current",
        "page",
      );
      await checkA11y();
      await waitForHydration(page, 'input[name="document_id"]');
      await page.getByLabel("Document id or sha256").fill(RECORDED.sha256);
      await page.getByRole("button", { name: "Open the document" }).click();
      await expect(page).toHaveURL(new RegExp(`${VIEWER}$`));
      await expect(page.getByRole("heading", { level: 1, name: RECORDED.title })).toBeVisible();
      await expect(
        page.getByRole("navigation", { name: "Breadcrumb" }).getByText(RECORDED.external_ref),
      ).toBeVisible();
      const clauses = page.locator("[data-slot='clause-list'] > li");
      await expect(clauses).toHaveCount(RECORDED.clauses.length);
      await expect(clauses.first()).toHaveAttribute("id", "clause-en.p1");
      await expect(clauses.first().locator("[data-slot='clause-page']")).toHaveText("Page 1");
      await expect(page.getByText(DOCUMENT_ID).first()).toBeVisible();
      await expect(page.locator("mark")).toHaveCount(0);
      await checkA11y();
    });

    test("answers an id the rulebook does not hold on the form", async ({ page }) => {
      await page.goto("/admin/rulebook/documents");
      await waitForHydration(page, 'input[name="document_id"]');
      const field = page.getByLabel("Document id or sha256");
      const unknown = randomUUID();
      await field.fill(unknown);
      await page.getByRole("button", { name: "Open the document" }).click();
      await expect(page.getByText("The rulebook holds no document with this id.")).toBeVisible();
      await expect(field).toBeFocused();
      await expect(field).toHaveValue(unknown);
      await expect(page).toHaveURL(/\/admin\/rulebook\/documents$/);
      expect((await page.goto(`/admin/rulebook/documents/${unknown}`))?.status()).toBe(404);
    });

    test("jumps to a clause and keeps the place in the address", async ({ page }) => {
      await page.goto(VIEWER);
      await waitForHydration(page, "[data-slot='jump-to-clause'] select");
      await page.getByLabel("Clause", { exact: true }).selectOption("clause-en.p3");
      await page.getByRole("button", { name: "Go to the clause" }).click();
      await expect(page).toHaveURL(new RegExp(`${VIEWER}#clause-en\\.p3$`));
      await expect(page.locator("[id='clause-en.p3']")).toBeFocused();
      await expect(page.getByRole("link", { name: "Clause en.p3" })).toHaveAttribute(
        "href",
        "#clause-en.p3",
      );
    });

    test("marks a mention's span from a link, and the whole clause when the span does not fit", async ({
      page,
      checkA11y,
    }) => {
      const ids = await clauseIds();
      const mention = MENTIONS.mentions.find((candidate) => candidate.clause_ref === "en.p3");
      if (mention === undefined) throw new Error("the recorded mentions have none in en.p3");
      const clauseId = ids[mention.clause_ref];
      await page.goto(
        `${VIEWER}?clause_id=${clauseId}&start=${mention.span_start}&end=${mention.span_end}`,
      );
      const clause = page.locator("[id='clause-en.p3']");
      await expect(clause).toHaveAttribute("data-marked", "span");
      await expect(clause.locator("mark")).toHaveText(mention.text);
      await expect(page.locator("mark")).toHaveCount(1);
      await expect(page.locator("[data-slot='highlight-note']")).toContainText(
        `clause en.p3 is the span from ${mention.span_start} to ${mention.span_end}`,
      );
      await expect(clause).toBeFocused();
      await checkA11y();

      await page.goto(`${VIEWER}?clause_id=${clauseId}&start=${mention.span_start}&end=100000`);
      await expect(clause).toHaveAttribute("data-marked", "clause");
      await expect(page.getByText("The span did not match")).toBeVisible();
      await checkA11y();

      await page.goto(`${VIEWER}?clause_id=${randomUUID()}`);
      await expect(page.getByText("The clause is not in this document")).toBeVisible();
      await expect(page.locator("mark")).toHaveCount(0);
      await page.goto(`${VIEWER}?clause_id=${clauseId}&start=1`);
      await expect(page.getByText("The link's mark is malformed")).toBeVisible();
    });
  });
});
