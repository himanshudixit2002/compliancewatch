import { ADMIN, ANALYST, IS_CI, OWNER, expect, seededTenantId, test } from "./fixtures";
import {
  STAGED_SOURCE_PREFIX,
  crawlIsOff,
  editStagedSource,
  pipelineGet,
  sources,
  stageUpload,
  stageUploadSource,
  syntheticHtml,
  syntheticPdf,
  unknownDocumentId,
  type DocumentRow,
} from "./pipeline-helpers";

/**
 * The source registry, one source's page, and the two handlers behind it (the stored bytes and the
 * upload) against the pipeline the stack runs: its built-in sources on the memory store, crawling
 * off, no Temporal for an ingest. The reading tests compare the pages with the pipeline's answers;
 * the writing tests act on a synthetic upload-only source staged for each run, so they run again on
 * the same stack. A fetch of a built-in source is sent only once the pipeline has said crawling is
 * off, and is refused before any site is read.
 */
const LIST = "/admin/sources";

test.describe("sources", () => {
  test("a tenant role gets a 404 for the list, a source and a stored file", async ({
    page,
    signIn,
  }) => {
    await signIn(OWNER);
    for (const path of [LIST, `${LIST}/example_notices`]) {
      expect((await page.goto(path))?.status(), path).toBe(404);
    }
    const raw = await page.request.get(`/api-bff/pipeline/documents/${unknownDocumentId()}/raw`);
    expect(raw.status()).toBe(404);
  });

  test("a key that cannot be a source's is the not-found page", async ({ page, signIn }) => {
    await signIn(ANALYST);
    await page.goto(`${LIST}/Not-A-Key`);
    await expect(page.getByRole("heading", { level: 1, name: "Page not found" })).toBeVisible();
  });

  test.describe("against the stack", () => {
    test.skip(
      !IS_CI && seededTenantId() === null,
      "needs the services: make web-stack, make web-stack-wait and make web-seed",
    );

    test("lists every source as the pipeline holds it, under the crawl switch, off by default", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const held = await sources();
      await signIn(ANALYST);
      await page.goto("/admin");
      await page.locator("aside").getByRole("link", { name: "Sources", exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${LIST}$`));
      await expect(page.getByRole("heading", { level: 1, name: "Sources" })).toBeVisible();
      const banner = page.locator("[data-slot='crawl-banner']");
      await expect(banner).toContainText("Crawling (pipeline.crawl)");
      await expect(banner).toContainText("Crawling is off by default");
      await expect(banner).toContainText("CW_PIPELINE_CRAWL_ENABLED");
      // Tests running beside this one stage sources of their own (and rename one), so the page may
      // hold more than the pipeline listed a moment before: every source listed is on it, and the
      // built-in ones are exactly those.
      const builtIn = held.filter((source) => !source.key.startsWith(STAGED_SOURCE_PREFIX));
      expect(builtIn.length).toBeGreaterThan(0);
      await expect(
        page.locator(`tr[data-source]:not([data-source^='${STAGED_SOURCE_PREFIX}'])`),
      ).toHaveCount(builtIn.length);
      for (const source of held) {
        const row = page.locator(`tr[data-source='${source.key}']`);
        await expect(row).toHaveCount(1);
        if (source.key.startsWith(STAGED_SOURCE_PREFIX)) continue;
        await expect(row).toContainText(source.name);
        await expect(row).toContainText(source.adapter_type);
        if (!source.listable) await expect(row).toContainText("Uploaded, never crawled");
      }
      await expect(page.locator("[data-slot='add-source-note']")).toHaveCount(0);
      await checkA11y();
    });

    test("an analyst reads a listing source with its documents and runs, and changes nothing", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const listing = (await sources()).find((source) => source.listable);
      if (listing === undefined) throw new Error("the stack holds no listing source");
      await signIn(ANALYST);
      await page.goto(LIST);
      await page.getByRole("link", { name: listing.name, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${LIST}/${listing.key}$`));
      await expect(page.getByRole("heading", { level: 1, name: listing.name })).toBeVisible();
      await expect(page.locator("[data-slot='source-facts']")).toContainText(listing.key);
      await expect(page.locator("[data-slot='source-read-only']")).toContainText(
        "Only an admin changes a source",
      );
      await expect(page.locator("[data-slot='fetch-panel']")).toHaveCount(0);
      await expect(page.locator("[data-slot='settings-panel']")).toHaveCount(0);
      await expect(page.getByRole("heading", { level: 2, name: "Documents" })).toBeVisible();
      await expect(page.getByRole("heading", { level: 2, name: "Crawl runs" })).toBeVisible();
      await page.getByRole("link", { name: "Every run of this source" }).click();
      await expect(page).toHaveURL(
        new RegExp(`/admin/pipeline\\?view=runs&source=${listing.key}$`),
      );
      await expect(page.getByLabel("Source")).toHaveValue(listing.key);
      await page.goBack();
      await checkA11y();
    });

    test("an admin's Fetch now is refused while crawling is off, and the page says what that means", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      expect(await crawlIsOff(), "crawling must be off on the stack: nothing is fetched here").toBe(
        true,
      );
      const listing = (await sources()).find((source) => source.listable);
      if (listing === undefined) throw new Error("the stack holds no listing source");
      const before = await pipelineGet<{ items: unknown[] }>(
        `/v1/pipeline/runs?source_key=${listing.key}&limit=200`,
      );
      await signIn(ADMIN);
      await page.goto(`${LIST}/${listing.key}`);
      const panel = page.locator("[data-slot='fetch-panel']");
      await expect(panel).toContainText("off by default");
      await panel.getByRole("button", { name: "Fetch now" }).click();
      const dialog = page.getByRole("dialog", { name: "Fetch this source now?" });
      await dialog.getByRole("textbox").fill("Example check of the crawl switch");
      await checkA11y();
      await dialog.getByRole("button", { name: "Fetch now" }).click();
      const outcome = page.locator("[data-slot='fetch-outcome']");
      await expect(outcome).toContainText("Crawling is off, so nothing was fetched");
      await expect(outcome).toContainText("CW_PIPELINE_CRAWL_ENABLED");
      await expect(outcome).toContainText("no regulator site was read");
      const after = await pipelineGet<{ items: unknown[] }>(
        `/v1/pipeline/runs?source_key=${listing.key}&limit=200`,
      );
      expect(after.items).toHaveLength(before.items.length);
      await checkA11y();
    });

    test("an admin changes a staged source's settings with a reason, and only what changed is saved", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageUploadSource();
      await signIn(ADMIN);
      await page.goto(`${LIST}/${staged.key}`);
      const panel = page.locator("[data-slot='settings-panel']");
      await expect(panel).toContainText("An upload-only source is never crawled");
      const renamed = `${staged.name} renamed`;
      await panel.getByLabel(/^Name/).fill(renamed);
      await panel.getByRole("checkbox", { name: /^Paused/ }).check();
      await panel.getByLabel(/^Why/).fill("Example rename of a staged source");
      await panel.getByRole("button", { name: "Save the settings" }).click();
      await page
        .getByRole("dialog", { name: "Save these settings?" })
        .getByRole("button", { name: "Save the settings" })
        .click();
      await expect(page.locator("[data-slot='settings-outcome']")).toContainText(
        "Saved: name and paused.",
      );
      await expect(page.getByRole("heading", { level: 1, name: renamed })).toBeVisible();
      const now = (await sources()).find((source) => source.key === staged.key);
      expect(now?.name).toBe(renamed);
      expect(now?.paused).toBe(true);
      await checkA11y();
      await panel.getByLabel(/^Why/).fill("Example save with nothing changed");
      await panel.getByRole("button", { name: "Save the settings" }).click();
      await page
        .getByRole("dialog", { name: "Save these settings?" })
        .getByRole("button", { name: "Save the settings" })
        .click();
      await expect(page.locator("[data-slot='settings-outcome']")).toContainText("Nothing to save");
    });

    test("a form opened before another admin's change saves only what this admin changed, and refuses a setting changed meanwhile", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageUploadSource();
      await signIn(ADMIN);
      await page.goto(`${LIST}/${staged.key}`);
      const panel = page.locator("[data-slot='settings-panel']");
      const outcome = page.locator("[data-slot='settings-outcome']");
      const pausedBox = panel.getByRole("checkbox", { name: /^Paused/ });
      await expect(pausedBox).not.toBeChecked();
      // Another admin pauses the source while this form still shows it running.
      await editStagedSource(staged.key, { paused: true });
      const renamed = `${staged.name} kept paused`;
      await panel.getByLabel(/^Name/).fill(renamed);
      await panel.getByLabel(/^Why/).fill("Example rename from a form opened earlier");
      await panel.getByRole("button", { name: "Save the settings" }).click();
      await page
        .getByRole("dialog", { name: "Save these settings?" })
        .getByRole("button", { name: "Save the settings" })
        .click();
      await expect(outcome).toContainText("Saved: name.");
      let now = (await sources()).find((source) => source.key === staged.key);
      expect(now?.name).toBe(renamed);
      expect(now?.paused, "the other admin's pause stands").toBe(true);
      // The page rendered the source again, so the form shows the pause it did not know of.
      await expect(pausedBox).toBeChecked();
      // Another admin sets the cadence; this form, showing the old one, asks for another.
      await editStagedSource(staged.key, { cadence_seconds: 14_400 });
      await panel.getByLabel(/^Cadence/).fill("3600");
      await panel.getByLabel(/^Why/).fill("Example cadence from a form opened earlier");
      await panel.getByRole("button", { name: "Save the settings" }).click();
      await page
        .getByRole("dialog", { name: "Save these settings?" })
        .getByRole("button", { name: "Save the settings" })
        .click();
      await expect(outcome).toContainText(
        "The cadence changed meanwhile: it is now 14400 seconds (4 h).",
      );
      await expect(outcome).toContainText("Nothing was saved.");
      now = (await sources()).find((source) => source.key === staged.key);
      expect(now?.cadence_seconds).toBe(14_400);
      await expect(panel.getByLabel(/^Cadence/)).toHaveValue("14400");
      await checkA11y();
    });

    test("an admin uploads a document to a staged statute source, and its stored bytes stream back", async ({
      page,
      signIn,
      checkA11y,
    }) => {
      const staged = await stageUploadSource();
      const pdf = syntheticPdf("upload through the page");
      await signIn(ADMIN);
      await page.goto(`${LIST}/${staged.key}`);
      await expect(page.locator("[data-slot='upload-only']")).toBeVisible();
      const panel = page.locator("[data-slot='upload-panel']");
      await panel.getByLabel(/^File/).setInputFiles({
        name: "example-statute.pdf",
        mimeType: "application/pdf",
        buffer: pdf.bytes,
      });
      await panel.getByLabel(/^Title/).fill("Example statute uploaded through the page");
      await panel.getByLabel(/^Reference/).fill("Example Act, 2000");
      await panel.getByLabel(/^Published on/).fill("2000-01-01");
      await panel.getByLabel(/^Why/).fill("Example statute the seed rules cite");
      await panel.getByRole("button", { name: "Upload the document" }).click();
      const dialog = page.getByRole("dialog", { name: "Upload example-statute.pdf?" });
      await expect(dialog).toContainText("never deleted");
      await dialog.getByRole("button", { name: "Upload the document" }).click();
      const outcome = page.locator("[data-slot='upload-outcome']");
      // The stack has no Temporal: the pipeline stores the file and says its ingest did not start.
      await expect(outcome).toContainText(
        /Stored, but its ingest did not start|Stored, and its ingest started/,
      );
      const stored = (
        await pipelineGet<{ items: DocumentRow[] }>(`/v1/pipeline/sources/${staged.key}/documents`)
      ).items;
      expect(stored.map((document) => document.document_id)).toEqual([pdf.documentId]);
      const row = page.locator(`tr[data-document='${pdf.documentId}']`);
      await expect(row).toContainText("Example statute uploaded through the page");
      await expect(row).toContainText("Discovered");
      await checkA11y();

      const raw = await page.request.get(`/api-bff/pipeline/documents/${pdf.documentId}/raw`);
      expect(raw.status()).toBe(200);
      expect(raw.headers()["content-type"]).toBe("application/pdf");
      expect(raw.headers()["x-content-type-options"]).toBe("nosniff");
      expect(raw.headers()["cache-control"]).toBe("private, no-store");
      expect(raw.headers()["content-disposition"]).toBe(
        `inline; filename="${pdf.documentId}.pdf"; filename*=UTF-8''Example%20statute%20uploaded%20through%20the%20page.pdf`,
      );
      expect(Buffer.from(await raw.body()).equals(pdf.bytes)).toBe(true);
    });

    test("the upload refuses another site, an analyst and a file that is not a document", async ({
      page,
      signIn,
    }) => {
      const staged = await stageUploadSource();
      const url = `/api-bff/pipeline/sources/${staged.key}/uploads`;
      const multipart = (file: { name: string; mimeType: string; buffer: Buffer }) => ({
        reason: "Example reason for the upload",
        file,
      });
      const pdf = {
        name: "example.pdf",
        mimeType: "application/pdf",
        buffer: syntheticPdf("refused").bytes,
      };
      await signIn(ADMIN);
      const crossSite = await page.request.post(url, {
        headers: { "sec-fetch-site": "cross-site", origin: "https://example.com" },
        multipart: multipart(pdf),
      });
      expect(crossSite.status()).toBe(403);
      expect(((await crossSite.json()) as { type: string }).type).toBe(
        "urn:compliancewatch:problem:web-cross-origin-request",
      );
      const text = await page.request.post(url, {
        headers: { "sec-fetch-site": "same-origin" },
        multipart: multipart({
          name: "example.txt",
          mimeType: "text/plain",
          buffer: Buffer.from("x"),
        }),
      });
      expect(text.status()).toBe(415);
      const shortReason = await page.request.post(url, {
        headers: { "sec-fetch-site": "same-origin" },
        multipart: { reason: "short", file: pdf },
      });
      expect(shortReason.status()).toBe(422);
      expect(
        (await pipelineGet<{ items: unknown[] }>(`/v1/pipeline/sources/${staged.key}/documents`))
          .items,
      ).toHaveLength(0);
      await page.context().clearCookies();
      await signIn(ANALYST);
      const analyst = await page.request.post(url, {
        headers: { "sec-fetch-site": "same-origin" },
        multipart: multipart(pdf),
      });
      expect(analyst.status()).toBe(403);
    });

    test("a stored HTML page is served sandboxed: its script does not run and nothing loads", async ({
      page,
      signIn,
      baseURL,
    }) => {
      const staged = await stageUploadSource();
      const html = syntheticHtml("Example page served sandboxed");
      const { documentId } = await stageUpload(staged.key, "Example page served sandboxed", html);
      await signIn(ANALYST);
      const path = `/api-bff/pipeline/documents/${documentId}/raw`;
      const raw = await page.request.get(path);
      expect(raw.status()).toBe(200);
      expect(raw.headers()["content-type"]).toBe("text/html");
      expect(raw.headers()["content-security-policy"]).toBe("sandbox; default-src 'none'");
      expect(raw.headers()["content-disposition"]).toBe(
        `inline; filename="${documentId}.html"; filename*=UTF-8''Example%20page%20served%20sandboxed.html`,
      );
      expect(raw.headers()["x-frame-options"]).toBe("DENY");
      const origin = new URL(baseURL ?? "http://localhost").origin;
      const elsewhere: string[] = [];
      page.on("requestfailed", (request) => {
        if (new URL(request.url()).origin === origin) return;
        elsewhere.push(`${request.url()} ${request.failure()?.errorText ?? ""}`);
      });
      await page.goto(path);
      // The page's script would rename it; its image (a host that never resolves) is refused by
      // the policy before any request leaves, rather than failing to resolve.
      await expect(page).toHaveTitle("Example page served sandboxed");
      await expect.poll(() => elsewhere).toEqual(["https://example.invalid/example.png csp"]);
    });

    test("the stored file is a 404 for an unknown document, and sends a visitor without a session to sign in", async ({
      page,
      signIn,
      playwright,
      baseURL,
    }) => {
      await signIn(ANALYST);
      const unknown = await page.request.get(
        `/api-bff/pipeline/documents/${unknownDocumentId()}/raw`,
      );
      expect(unknown.status()).toBe(404);
      expect(((await unknown.json()) as { title: string }).title).toBe(
        "No stored document has this id",
      );
      const anonymous = await playwright.request.newContext({ baseURL });
      const path = `/api-bff/pipeline/documents/${unknownDocumentId()}/raw`;
      const answer = await anonymous.get(path, { maxRedirects: 0 });
      expect(answer.status()).toBe(303);
      expect(answer.headers()["location"]).toBe(`/sign-in?next=${encodeURIComponent(path)}`);
      await anonymous.dispose();
    });
  });
});
