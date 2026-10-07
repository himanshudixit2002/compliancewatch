import { randomUUID } from "node:crypto";
import { ADMIN, ANALYST, IS_CI, OWNER, expect, seededTenantId, test } from "./fixtures";
import { pipelineGet, stageUpload, stageUploadSource } from "./pipeline-helpers";

/**
 * The pipeline's operations and a stored document's page against the pipeline the stack runs
 * (memory store, crawling off, no Temporal, no relay). The reading tests compare each view with the
 * pipeline's answer; the retry tests act on a synthetic document uploaded to a source staged for
 * each run, so they run again on the same stack. Without Temporal no ingest starts: a retry from
 * parse is answered that Temporal did not answer, and a retry the pipeline refuses before any
 * ingest (nothing to extract, a type no rule is extracted from) is said as it is.
 */
const PAGE = "/admin/pipeline";

test.describe("pipeline", () => {
  test("a tenant role gets a 404 for the operations, a document and the tasks", async ({
    page,
    signIn,
  }) => {
    await signIn(OWNER);
    for (const path of [PAGE, `${PAGE}/documents/${randomUUID()}`, `${PAGE}/tasks`]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
  });

  test("a malformed document id is the not-found page", async ({ page, signIn }) => {
    await signIn(ANALYST);
    await page.goto(`${PAGE}/documents/not-a-document`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services: make web-stack, make web-stack-wait and make web-seed",
    );

    test("lists the crawl runs as the pipeline holds them, and keeps the filter in the address", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      await signIn(ANALYST);
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Pipeline", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Pipeline" })).toBeVisible();
      const chips = page.getByRole("navigation", { name: "Views of the pipeline" });
      await expect(chips.getByRole("link", { name: "Crawl runs" })).toHaveAttribute(
        "aria-current",
        "true",
      );
      const runs = await pipelineGet<{ items: { run_id: string }[] }>("/v1/pipeline/runs?limit=25");
      if (runs.items.length === 0) {
        await expect(page.getByRole("heading", { name: "No crawl has run" })).toBeVisible();
      } else {
        await expect(page.locator("tr[data-run]")).toHaveCount(runs.items.length);
      }
      await checkA11y();
      await page.getByLabel("Why it ran").selectOption("backfill");
      await page.getByRole("button", { name: "Show" }).click();
      // The GET form sends its empty selects too; the page reads them as no filter.
      await expect(page).toHaveURL(new RegExp(`${PAGE}\\?source=&status=&trigger=backfill$`));
      await expect(page.getByLabel("Why it ran")).toHaveValue("backfill");
      const backfills = await pipelineGet<{ items: unknown[] }>(
        "/v1/pipeline/runs?trigger=backfill&limit=25",
      );
      if (backfills.items.length === 0) {
        await expect(
          page.getByRole("heading", { name: "No crawl run matches the filter" }),
        ).toBeVisible();
      } else {
        await expect(page.locator("tr[data-trigger='backfill']")).toHaveCount(
          backfills.items.length,
        );
      }
    });

    test("lists a staged document with how the pipeline reads it, and refuses a date out of shape", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageUploadSource();
      const { documentId } = await stageUpload(
        staged.key,
        "Example statute listed by the pipeline",
      );
      await signIn(ANALYST);
      await page.goto(`${PAGE}?view=documents&source=${staged.key}`);
      await expect(
        page
          .getByRole("navigation", { name: "Views of the pipeline" })
          .getByRole("link", { name: "Documents" }),
      ).toHaveAttribute("aria-current", "true");
      const row = page.locator(`tr[data-document='${documentId}']`);
      await expect(row).toContainText("Example statute listed by the pipeline");
      await expect(row).toContainText("Statute");
      await expect(row).toContainText("Discovered");
      await expect(row).toContainText("Not classified yet");
      await expect(row).toContainText("None by the current prompt");
      await expect(page.locator("tr[data-document]")).toHaveCount(1);
      await checkA11y();
      await page.getByLabel("Published from").fill("2000-02-01");
      await page.getByLabel("Published to").fill("2000-01-01");
      await page.getByRole("button", { name: "Show" }).click();
      await expect(
        page.getByText("Give a date (YYYY-MM-DD) on or after the first one, or leave it empty."),
      ).toBeVisible();
      await expect(page.locator("tr[data-document]")).toHaveCount(0);
      await page.goto(`${PAGE}?view=documents&source=${staged.key}`);
      await page.getByRole("link", { name: "Example statute listed by the pipeline" }).click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}/documents/${documentId}$`));
    });

    test("shows the dead outbox as the pipeline holds it, and checks the topic", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const dead = await pipelineGet<{ items: { event_id: string }[] }>(
        "/v1/pipeline/outbox/dead?limit=25",
      );
      await signIn(ANALYST);
      await page.goto(`${PAGE}?view=outbox`);
      if (dead.items.length === 0) {
        await expect(page.getByRole("heading", { name: "No outbox row is dead" })).toBeVisible();
      } else {
        await expect(page.locator("tr[data-event]")).toHaveCount(dead.items.length);
      }
      await expect(page.locator("[data-slot='pipeline-read-only']")).toContainText(
        "Only an admin retries, requeues or resolves",
      );
      await checkA11y();
      await page.getByLabel(/^Topic/).fill("Not A Topic");
      await page.getByRole("button", { name: "Show" }).click();
      await expect(page.getByText(/A topic is lower-case letters/)).toBeVisible();
      await page.getByLabel(/^Topic/).fill("document.parsed");
      await page.getByRole("button", { name: "Show" }).click();
      await expect(page).toHaveURL(new RegExp(`${PAGE}\\?view=outbox&topic=document.parsed$`));
    });

    test("an analyst reads a stored document without the retry", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageUploadSource();
      const { documentId } = await stageUpload(staged.key, "Example statute read by an analyst");
      await signIn(ANALYST);
      await page.goto(`${PAGE}/documents/${documentId}`);
      await expect(
        page.getByRole("heading", { level: 1, name: "Example statute read by an analyst" }),
      ).toBeVisible();
      const facts = page.locator("[data-slot='document-facts']");
      await expect(facts).toContainText(documentId);
      await expect(facts).toContainText(staged.key);
      await expect(
        facts.getByRole("link", { name: "Open the stored file (new tab)" }),
      ).toHaveAttribute("href", `/api-bff/pipeline/documents/${documentId}/raw`);
      await expect(page.locator("[data-slot='no-classification']")).toBeVisible();
      await expect(page.getByRole("heading", { name: "No retry yet" })).toBeVisible();
      await expect(page.locator("[data-slot='retry-panel']")).toHaveCount(0);
      await expect(page.locator("[data-slot='document-read-only']")).toBeVisible();
      await checkA11y();
      expect((await page.goto(`${PAGE}/documents/${randomUUID()}`))?.status()).toBe(200);
      await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
    });

    test("an admin's retry is refused plainly when nothing is left to extract or no rule is extracted", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageUploadSource();
      const { documentId } = await stageUpload(staged.key, "Example statute retried from extract");
      await signIn(ADMIN);
      await page.goto(`${PAGE}/documents/${documentId}`);
      const panel = page.locator("[data-slot='retry-panel']");
      await panel.getByRole("radio", { name: "Extract" }).click();
      await panel.getByLabel(/^Why/).fill("Example retry of the extraction");
      await panel.getByRole("button", { name: "Retry the document" }).click();
      await page
        .getByRole("dialog", { name: "Retry Example statute retried from extract?" })
        .getByRole("button", { name: "Retry the document" })
        .click();
      const outcome = page.locator("[data-slot='retry-outcome']");
      await expect(outcome).toContainText("A triage task holds it, or nothing is left to extract");
      await checkA11y();
      await panel.getByLabel(/^Read it as/).selectOption("statute");
      await expect(panel).toContainText("No rule is extracted from this type");
      await panel.getByRole("button", { name: "Retry the document" }).click();
      await page.getByRole("dialog").getByRole("button", { name: "Retry the document" }).click();
      await expect(outcome).toContainText("No rule is extracted from this type");
      const detail = await pipelineGet<{ retries: unknown[] }>(
        `/v1/pipeline/documents/${documentId}`,
      );
      expect(detail.retries).toHaveLength(0);
    });

    test("an admin's retry from parse says Temporal did not answer, and sends the same request again", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageUploadSource();
      const { documentId } = await stageUpload(staged.key, "Example statute retried from parse");
      // The Idempotency-Key of each retry the page sends (the action's form data carries it).
      const keys: string[] = [];
      page.on("request", (request) => {
        if (request.method() !== "POST" || request.headers()["next-action"] === undefined) return;
        const key = /name="[^"]*idempotency_key"\r\n\r\n([0-9a-f-]{36})/.exec(
          request.postData() ?? "",
        )?.[1];
        if (key !== undefined) keys.push(key);
      });
      await signIn(ADMIN);
      await page.goto(`${PAGE}/documents/${documentId}`);
      const panel = page.locator("[data-slot='retry-panel']");
      await expect(panel.getByRole("radio", { name: "Parse" })).toBeChecked();
      await panel.getByLabel(/^Why/).fill("Example retry of the whole ingest");
      await panel.getByRole("button", { name: "Retry the document" }).click();
      const dialog = page.getByRole("dialog", {
        name: "Retry Example statute retried from parse?",
      });
      await expect(dialog).toContainText("from Parse");
      await dialog.getByRole("button", { name: "Retry the document" }).click();
      const outcome = page.locator("[data-slot='retry-outcome']");
      await expect(outcome).toContainText("Temporal did not answer: send the same request again");
      await checkA11y();
      await outcome.getByRole("button", { name: "Send the same request again" }).click();
      await expect.poll(() => keys.length).toBe(2);
      await expect(
        outcome.getByRole("button", { name: "Send the same request again" }),
      ).toBeEnabled();
      await expect(outcome).toContainText("Temporal did not answer: send the same request again");
      // The page rendered again after each answer, with a new key; the form's own Retry still
      // sends the first, so it is the same request and never a second attempt.
      await panel.getByRole("button", { name: "Retry the document" }).click();
      await dialog.getByRole("button", { name: "Retry the document" }).click();
      await expect.poll(() => keys.length).toBe(3);
      await expect(panel.getByRole("button", { name: "Retry the document" })).toBeEnabled();
      await expect(outcome).toContainText("Temporal did not answer: send the same request again");
      expect(new Set(keys).size, `one key for the three sends: ${keys.join(", ")}`).toBe(1);
    });
  });
});
