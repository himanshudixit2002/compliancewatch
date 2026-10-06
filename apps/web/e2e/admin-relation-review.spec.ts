import { randomUUID } from "node:crypto";
import { ANALYST, IS_CI, OWNER, REVIEWER, expect, seededTenantId, test } from "./fixtures";
import {
  RECORDED_DOCUMENT,
  latestVersion,
  rulebookGet,
  stageReview,
  versionsOf,
} from "./rulebook-helpers";

/**
 * The relation candidate queue and a candidate's page against the rulebook the stack runs (`make
 * web-seed` stages the recorded notification's candidate), with web.admin_rulebook_writes on for
 * the run. The reading tests compare the pages with the rulebook's answers; the deciding tests
 * stage a synthetic document of their own for each run and approve or reject its candidates, so
 * the recorded candidate stays open for the next run. An approval starts from the draft of a rule
 * no other spec moves (position 6 in key order) and points at the next rule's draft; it writes a
 * rule relation on the memory store that a fresh stack forgets.
 */
const QUEUE = "/admin/rulebook/relations";
const FROM_POSITION = 6;
const TARGET_POSITION = 7;

interface CandidateRow {
  candidate_id: string;
  document_id: string;
  status: string;
  evidence_quote: string;
  reject_reason: string | null;
  target_rule_key: string | null;
}

test.describe("relation candidates", () => {
  test("a tenant role gets a 404 for the queue and a candidate", async ({ page, signIn }) => {
    await signIn(OWNER);
    for (const path of [QUEUE, `${QUEUE}/${randomUUID()}`]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test("a malformed candidate id is the not-found page", async ({ page, signIn, checkA11y }) => {
    await signIn(ANALYST);
    await page.goto(`${QUEUE}/not-a-candidate`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    await checkA11y();
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
    );

    test("a candidate id no status holds is the not-found page", async ({ page, signIn }) => {
      await signIn(ANALYST);
      await page.goto(`${QUEUE}/${randomUUID()}`);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    });

    test("lists the recorded notification's candidates by status as the rulebook holds them", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      await signIn(ANALYST);
      await page.goto("/admin");
      await page
        .locator("aside")
        .getByRole("link", { name: "Relation candidates", exact: true })
        .click();
      await expect(page).toHaveURL(new RegExp(`${QUEUE}$`));
      await expect(
        page.getByRole("heading", { level: 1, name: "Relation candidates" }),
      ).toBeVisible();
      await checkA11y();

      // One document's candidates: the recorded notification's, which no spec decides.
      await page.getByLabel(/^Document id/).fill(RECORDED_DOCUMENT.documentId);
      await page.getByRole("button", { name: "Show candidates" }).click();
      await expect(page).toHaveURL(
        new RegExp(`${QUEUE}\\?document=${RECORDED_DOCUMENT.documentId}$`),
      );
      const open = await rulebookGet<CandidateRow[]>(
        `/v1/rulebook/review/relations?status=open&document_id=${RECORDED_DOCUMENT.documentId}&limit=25`,
      );
      expect(open.length, "the seed stages the recorded notification's candidate").toBeGreaterThan(
        0,
      );
      const rows = page.locator("[data-candidate]");
      await expect(rows).toHaveCount(open.length);
      for (const candidate of open) {
        await expect(page.locator(`[data-candidate='${candidate.candidate_id}']`)).toContainText(
          candidate.evidence_quote,
        );
      }

      const chips = page.getByRole("navigation", { name: "Show candidates by status" });
      await chips.getByRole("link", { name: "Rejected", exact: true }).click();
      await expect(page).toHaveURL(
        new RegExp(`${QUEUE}\\?status=rejected&document=${RECORDED_DOCUMENT.documentId}$`),
      );
      await expect(chips.getByRole("link", { name: "Rejected", exact: true })).toHaveAttribute(
        "aria-current",
        "true",
      );
      const rejected = await rulebookGet<CandidateRow[]>(
        `/v1/rulebook/review/relations?status=rejected&document_id=${RECORDED_DOCUMENT.documentId}&limit=25`,
      );
      if (rejected.length === 0) {
        await expect(
          page.getByRole("heading", { name: "No candidate is rejected yet" }),
        ).toBeVisible();
      } else {
        await expect(rows).toHaveCount(rejected.length);
      }
      await checkA11y();
    });

    test("opens the recorded candidate with its evidence marked and the versions it may take", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const [candidate] = await rulebookGet<CandidateRow[]>(
        `/v1/rulebook/review/relations?status=open&document_id=${RECORDED_DOCUMENT.documentId}&limit=1`,
      );
      if (candidate === undefined) throw new Error("the recorded candidate is not open");
      await signIn(REVIEWER);
      await page.goto(`${QUEUE}?document=${RECORDED_DOCUMENT.documentId}`);
      await page
        .locator(`[data-candidate='${candidate.candidate_id}']`)
        .getByRole("link")
        .first()
        .click();
      await expect(page).toHaveURL(new RegExp(`${QUEUE}/${candidate.candidate_id}\\?status=open$`));
      await expect(
        page.getByRole("heading", { level: 1, name: "Relation candidate" }),
      ).toBeVisible();
      await expect(page.locator("[data-slot='evidence-clause'] mark")).toHaveText(
        candidate.evidence_quote,
      );
      await expect(page.getByRole("heading", { level: 2, name: "Approve" })).toBeVisible();
      if (candidate.target_rule_key !== null) {
        const versions = await versionsOf(candidate.target_rule_key);
        const target = page.getByLabel(/^The version it points at/);
        for (const version of versions) {
          await expect(target.locator(`option[value='${version.rule_version_id}']`)).toHaveCount(1);
        }
      }
      const draft = await latestVersion(FROM_POSITION);
      await expect(
        page
          .getByLabel(/^The draft it starts from/)
          .locator(`option[value='${draft.rule_version_id}']`),
      ).toHaveCount(1);
      await checkA11y();
    });

    test("rejects a candidate staged for the run with a reason", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageReview(1, [{ relation: "refers_to", target: 0 }]);
      const candidateId = staged.candidateIds[0] as string;
      await signIn(ANALYST);
      await page.goto(`${QUEUE}/${candidateId}`);
      await expect(page.locator("[data-slot='candidate-facts']")).toContainText("Open");
      await page.getByLabel(/^Why reject/).selectOption("not_in_text");
      await page.getByRole("button", { name: "Reject the candidate" }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toContainText("rejected (Not in the text)");
      await checkA11y();
      await dialog.getByRole("button", { name: "Reject the candidate" }).click();
      await expect(page.locator("[data-slot='candidate-done']")).toContainText(
        "Rejected: Not in the text.",
      );
      await expect(page.locator("[data-slot='candidate-facts']")).toContainText("Rejected");
      const [stored] = await rulebookGet<CandidateRow[]>(
        `/v1/rulebook/review/relations?status=rejected&document_id=${staged.documentId}&limit=1`,
      );
      expect(stored?.candidate_id).toBe(candidateId);
      expect(stored?.reject_reason).toBe("not_in_text");
      await checkA11y();
    });

    test("approves a candidate staged for the run from a draft onto another rule's draft", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageReview(1, [{ relation: "refers_to", target: 0 }]);
      const candidateId = staged.candidateIds[0] as string;
      const from = await latestVersion(FROM_POSITION);
      const target = await latestVersion(TARGET_POSITION);
      await signIn(ANALYST);
      await page.goto(`${QUEUE}/${candidateId}?status=open`);
      await expect(
        page.getByText(
          "The target is not aligned to an entity: name a version, or align the name in the entity review first.",
        ),
      ).toBeVisible();
      await page.getByLabel(/^The draft it starts from/).selectOption(from.rule_version_id);
      await page.getByLabel(/^The version it points at/).selectOption(target.rule_version_id);
      await page.getByRole("button", { name: "Approve the candidate" }).click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toContainText(`from ${from.rule_key} v${from.version}`);
      await dialog.getByRole("button", { name: "Approve the candidate" }).click();
      const done = page.locator("[data-slot='candidate-done']");
      await expect(done).toContainText("Approved: rule relation");
      await expect(page.locator("[data-slot='candidate-facts']")).toContainText("Approved");
      const relations = await rulebookGet<
        { candidate_id: string | null; to_rule_version_id: string | null }[]
      >(
        `/v1/rulebook/relations?from_rule_version_id=${from.rule_version_id}&published_only=false&limit=200`,
      );
      const written = relations.find((relation) => relation.candidate_id === candidateId);
      expect(written?.to_rule_version_id).toBe(target.rule_version_id);
      await checkA11y();
      await done.getByRole("link", { name: "Open the relations graph around the draft" }).click();
      await expect(page).toHaveURL(
        new RegExp(`/admin/rulebook/relations/graph\\?rule_version_id=${from.rule_version_id}$`),
      );
    });
  });
});
