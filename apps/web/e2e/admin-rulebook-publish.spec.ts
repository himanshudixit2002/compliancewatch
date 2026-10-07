import type { Page } from "@playwright/test";
import {
  ANALYST,
  IS_CI,
  REVIEWER,
  expect,
  seededTenantId,
  test,
  waitForHydration,
} from "./fixtures";
import { holdingPosition } from "./position-lock";
import {
  RECORDED_DOCUMENT,
  latestVersion,
  recordedClauseIds,
  rulebookGet,
  versionNow,
  type VersionRow,
} from "./rulebook-helpers";

/**
 * The publish workflow of a rule version against the rulebook `make web-stack` starts with the
 * seed calendar's drafts and publishing on (web.publish_actions is on for the e2e run). Each test
 * takes its own draft (by its rule's position in key order, held while it works, so two copies of
 * a test never move it at once) and first returns it to draft through the page when an earlier
 * run left it in review, so the specs run in parallel and again on the same stack. An analyst
 * submits and returns; approving is a reviewer's (D-043), so the approvals are a reviewer's.
 * Nothing is published or withdrawn: the memory store could not undo it, and nothing is marked
 * reviewed by hand; every analyst and reviewer is a synthetic user of the fake sign-in.
 */
const LIST = "/admin/rulebook/versions";
const CITE_POSITION = 2;
const HIGH_IMPACT_POSITION = 3;
const RETURN_POSITION = 4;
/** Room for a copy of the test that holds the position first. */
const HOLDING_TIMEOUT = 120_000;

function versionPath(version: VersionRow): string {
  return `${LIST}/${version.rule_version_id}`;
}

async function openAsDraft(page: Page, version: VersionRow): Promise<void> {
  await page.goto(versionPath(version));
  const facts = page.locator("[data-slot='version-facts']");
  if ((await versionNow(version.rule_version_id)).status !== "draft") {
    await waitForHydration(page, "[data-slot='workflow-steps'] button");
    await page.getByRole("button", { name: "Return to draft" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Reason").fill("Example reason: start the e2e run from a draft");
    await dialog.getByRole("button", { name: "Return to draft" }).click();
    await expect(facts).toContainText("Draft");
  }
  await expect(page.getByRole("button", { name: "Submit for review" })).toBeVisible();
}

test.describe("the publish workflow", () => {
  test.skip(
    !IS_CI && seededTenantId() === null,
    "needs the services and the seed: make web-stack, make web-stack-wait and make web-seed",
  );

  test.beforeEach(async ({ signIn }) => {
    await signIn(ANALYST);
  });

  test("cites the recorded notification: a quote not in its clause is refused, one in it is verified", async ({
    page,
    checkA11y,
  }) => {
    test.setTimeout(HOLDING_TIMEOUT);
    await holdingPosition(CITE_POSITION, async () => {
      const version = await latestVersion(CITE_POSITION);
      const clauses = await recordedClauseIds();
      // Whole words from the clause, so no number is cut and the quote is the clause's own text.
      const clauseText = RECORDED_DOCUMENT.textOf("en.p3");
      const matching = clauseText.slice(0, clauseText.lastIndexOf(" ", 160));
      const missing = "Example words this clause never holds, from the year 2000";
      await openAsDraft(page, version);
      await waitForHydration(page, "[data-slot='citations-editor'] input");
      const editor = page.locator("[data-slot='citations-editor']");
      await editor.getByLabel(/Clause id/).fill(clauses["en.p3"] as string);
      await editor.getByLabel(/^Quote/).fill(matching);
      await editor.getByRole("button", { name: "Add a citation" }).click();
      await editor
        .getByLabel(/Clause id/)
        .nth(1)
        .fill(clauses["en.p4"] as string);
      await editor
        .getByLabel(/^Quote/)
        .nth(1)
        .fill(missing);
      await editor.getByRole("button", { name: "Cite and verify" }).click();

      await expect(editor.getByRole("alert")).toContainText(
        "Citation quote not found in its clause",
      );
      const failures = editor.locator("[data-slot='citations-failures']");
      await expect(failures).toContainText(`en.p4 of ${RECORDED_DOCUMENT.documentId}`);
      const rows = editor.locator("[data-slot='citation-row']");
      await expect(rows.nth(1)).toContainText("Not found in its clause");
      await expect(rows.nth(0)).not.toContainText("Not found in its clause");
      await expect(editor.getByLabel(/^Quote/).nth(1)).toHaveValue(missing);
      await checkA11y();
      const refused = await rulebookGet<{ quote: string }[]>(
        `/v1/rulebook/rule-versions/${version.rule_version_id}/citations`,
      );
      expect(refused.map((citation) => citation.quote)).not.toContain(missing);

      await editor.getByRole("button", { name: "Remove citation 2" }).click();
      await editor.getByRole("button", { name: "Cite and verify" }).click();
      const result = editor.locator("[data-slot='citations-result']");
      await expect(result).toContainText("Every quote was found in its clause.");
      await expect(result).toContainText("Clause en.p3: verified, match score");
      const stored = await rulebookGet<
        { citation_id: string; quote: string; verified: boolean; clause_id: string }[]
      >(`/v1/rulebook/rule-versions/${version.rule_version_id}/citations`);
      const saved = stored.find((citation) => citation.quote === matching);
      expect(saved).toMatchObject({ verified: true, clause_id: clauses["en.p3"] });
      const cited = page.locator(
        `[data-slot='citations-table'] tr[data-citation='${saved?.citation_id}']`,
      );
      await expect(cited).toHaveAttribute("data-clause-ref", "en.p3");
      await expect(cited).toContainText("Verified");
      await expect(cited).toContainText(RECORDED_DOCUMENT.external_ref);
      await checkA11y();
    });
  });

  test("submits as high impact, leaves the approval to a reviewer, who is refused a second one", async ({
    page,
    signIn,
    checkA11y,
  }) => {
    test.setTimeout(HOLDING_TIMEOUT);
    await holdingPosition(HIGH_IMPACT_POSITION, async () => {
      const version = await latestVersion(HIGH_IMPACT_POSITION);
      await openAsDraft(page, version);
      await waitForHydration(page, "[data-slot='workflow-steps'] button");
      await page.getByRole("button", { name: "Submit for review" }).click();
      const submit = page.getByRole("dialog", {
        name: `Submit for review: version ${version.version}`,
      });
      const box = submit.getByRole("checkbox", {
        name: "High impact: publishing needs two different approvers",
      });
      if (!(await box.isDisabled())) await box.check();
      await expect(box).toBeChecked();
      await checkA11y();
      await submit.getByRole("button", { name: "Submit for review" }).click();
      const outcome = page.locator("[data-slot='workflow-outcome']");
      await expect(outcome).toContainText("Submitted for review as high impact");
      await expect(page.locator("[data-slot='version-facts']")).toContainText("In review");
      // An analyst returns a version under review but is not offered the approval.
      await expect(page.getByRole("button", { name: "Return to draft" })).toBeVisible();
      await expect(page.getByRole("button", { name: "Approve" })).toHaveCount(0);
      await expect(page.locator("[data-slot='workflow-reserved']")).toContainText(
        "Approving, publishing and withdrawing are a reviewer's or an admin's. Not offered to you here: Approve.",
      );

      await signIn(REVIEWER);
      await page.reload();
      await waitForHydration(page, "[data-slot='workflow-steps'] button");
      await expect(page.locator("[data-slot='workflow-reserved']")).toHaveCount(0);
      await page.getByRole("button", { name: "Approve" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
      await expect(outcome).toContainText("Your approval is recorded: 1 of 2 approvals.");
      await expect(outcome).toContainText(
        "It needs a second approver: a different reviewer or admin.",
      );
      await expect(outcome.locator("[data-slot='approvers']")).toContainText(
        `${REVIEWER.displayName} (you)`,
      );

      await page.getByRole("button", { name: "Approve" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
      const refusal = page.locator("[data-step='approve'] [data-slot='step-refusal']");
      await expect(refusal).toContainText("Approver already approved this review round");
      await expect(refusal.locator("[data-slot='correlation-id']")).toBeVisible();
      await expect(outcome).toContainText("1 of 2 approvals in this round.");
      await checkA11y();

      const now = await versionNow(version.rule_version_id);
      expect(now).toMatchObject({
        status: "in_review",
        high_impact: true,
        seed_status: "needs_review",
      });
    });
  });

  test("returns a version under review to draft with a reason", async ({ page, checkA11y }) => {
    test.setTimeout(HOLDING_TIMEOUT);
    await holdingPosition(RETURN_POSITION, async () => {
      const version = await latestVersion(RETURN_POSITION);
      await openAsDraft(page, version);
      await waitForHydration(page, "[data-slot='workflow-steps'] button");
      await page.getByRole("button", { name: "Submit for review" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Submit for review" }).click();
      await expect(page.locator("[data-slot='version-facts']")).toContainText("In review");

      await page.getByRole("button", { name: "Return to draft" }).click();
      const dialog = page.getByRole("dialog", {
        name: `Return to draft: version ${version.version}`,
      });
      const confirm = dialog.getByRole("button", { name: "Return to draft" });
      await dialog.getByLabel("Reason").fill("Too short");
      await expect(confirm).toBeDisabled();
      await dialog.getByLabel("Reason").fill("Example reason: the quote needs another clause");
      await expect(confirm).toBeEnabled();
      await checkA11y();
      await confirm.click();
      await expect(page.locator("[data-slot='workflow-outcome']")).toContainText(
        "Returned to draft: the round's approvals no longer count.",
      );
      await expect(page.locator("[data-slot='version-facts']")).toContainText("Draft");
      await expect(page.getByRole("button", { name: "Submit for review" })).toBeVisible();
      expect((await versionNow(version.rule_version_id)).status).toBe("draft");
    });
  });
});
