import { randomUUID } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Page } from "@playwright/test";
import { IS_CI, expect, test, waitForHydration } from "../fixtures";

/**
 * The product journey: the obligation, calendar, changes and ask screens on real data, against
 * `make product` (every service behind its internal listener, the worker turning decisions into
 * obligations) after `make product-seed` (the synthetic tenants, the demo publication of the seed
 * rules, the first decisions). CW_E2E_PRODUCT_URL names the listener; the Playwright config points
 * the app at it. The seed's state file names the synthetic business tenant, which the sign-in
 * form offers as the last seeded tenant.
 *
 * What the pages show is compared with what the services answer, read from the same listener as
 * the tenant. The writes (start, complete, comment) go to a probe business made for the run, as
 * `cw-product check` makes its own, so the seeded registration's obligations stay as they are; the
 * probe's first obligation is found by the onboarding summary's poll. The seed rules are the real
 * GST calendar's, so this spec names a return to ask about (the guard's allow list says why).
 */
const PRODUCT = process.env.CW_E2E_PRODUCT_URL?.trim().replace(/\/+$/, "") || null;

/** The synthetic reviewers of the demo publication (tools/demo cw_demo.product.analysts). */
const SYNTHETIC_APPROVERS = [
  "00000000-0000-4000-8000-00000000a002",
  "00000000-0000-4000-8000-00000000a003",
];

/** A monthly filer in Karnataka, as `cw-product check` answers for its probes. */
const PROBE_ANSWERS = [
  { key: "state_codes", value: ["29"] },
  { key: "registration_type", value: "regular" },
  { key: "filing_scheme", value: "regular_monthly" },
  { key: "return_filing_frequency", value: "monthly" },
];

const QUESTION = "When is my GSTR-3B due?";
const ANNUAL_RULE = "gstr9_annual";

interface SeedState {
  tenantId: string;
  entityId: string;
  registrationId: string;
}

interface ListedBody {
  obligation_id: string;
  business_id: string;
  title: string;
  status: string;
  due_at: string | null;
  rule_version_id: string;
}

interface DetailBody extends ListedBody {
  rule_version: { approved_by: string[]; seed_status: string; reviewed: boolean } | null;
  citations: { quote: string; clause_ref: string }[];
  history: { kind: string }[];
  comments: { body: string }[];
}

interface ChangeBody {
  change_id: string;
  kind: string;
  rule_key: string;
  rule_version_id: string;
  title: string;
}

function seedState(): SeedState | null {
  const configured = process.env.CW_WEB_SEED_STATE_PATH?.trim();
  const path = resolve(__dirname, "..", "..", configured || "../../var/seed/last.json");
  try {
    const state = JSON.parse(readFileSync(path, "utf8")) as Record<string, unknown>;
    const { tenant_id, entity_node_id, registration_node_id } = state;
    if (
      typeof tenant_id === "string" &&
      typeof entity_node_id === "string" &&
      typeof registration_node_id === "string"
    ) {
      return {
        tenantId: tenant_id,
        entityId: entity_node_id,
        registrationId: registration_node_id,
      };
    }
  } catch {
    // No seed state: make product-seed has not run here.
  }
  return null;
}

async function onProduct<T>(tenantId: string, path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${PRODUCT}${path}`, {
    ...init,
    headers: { "content-type": "application/json", "x-tenant-id": tenantId, ...init.headers },
  });
  expect(response.ok, `${path}: ${response.status} ${await response.clone().text()}`).toBe(true);
  return (await response.json()) as T;
}

/** A node's obligations as the public list orders them: due date first, then id. */
async function obligationsOf(tenantId: string, nodeId: string): Promise<ListedBody[]> {
  const page = await onProduct<{ items: ListedBody[] }>(
    tenantId,
    `/v1/businesses/${nodeId}/obligations?limit=200`,
  );
  return page.items;
}

function byDue(a: ListedBody, b: ListedBody): number {
  if (a.due_at !== b.due_at) {
    if (a.due_at === null) return 1;
    if (b.due_at === null) return -1;
    return Date.parse(a.due_at) - Date.parse(b.due_at);
  }
  return a.obligation_id < b.obligation_id ? -1 : 1;
}

/** The IST day of a due instant, YYYY-MM-DD. */
function istDay(instant: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(instant));
}

/** Signs in as an owner of the seeded tenant, picked with "Use the last seeded tenant". */
async function signInAsSeededOwner(page: Page, seed: SeedState, next: string): Promise<void> {
  await page.goto(`/sign-in?next=${encodeURIComponent(next)}`);
  await waitForHydration(page, 'input[name="tenantId"]');
  await page.getByRole("button", { name: "Use the last seeded tenant" }).click();
  await expect(page.getByLabel("Tenant id")).toHaveValue(seed.tenantId);
  await page.getByLabel("Tenant kind").selectOption("business");
  await page.getByRole("checkbox", { name: "Owner" }).check();
  await page.getByLabel("Display name").fill("Example product owner");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/sign-in"));
}

/** A Karnataka GSTIN no lookup knows, as `cw-product check` makes its probes'. */
function probeGstin(): string {
  const token = Number.parseInt(randomUUID().replace(/-/g, "").slice(0, 12), 16);
  const letters =
    String.fromCharCode(65 + (token % 26)) +
    String.fromCharCode(65 + (Math.floor(token / 26) % 26));
  const digits = String(Math.floor(token / 676) % 10_000).padStart(4, "0");
  return `29ZZZ${letters}${digits}Z1Z5`;
}

test.describe("the product journey", () => {
  const seed = seedState();
  test.skip(
    !IS_CI && (PRODUCT === null || seed === null),
    "needs make product WEB=0, make product-seed and CW_E2E_PRODUCT_URL (make product-e2e)",
  );
  test.beforeAll(() => {
    if (PRODUCT === null) throw new Error("CW_E2E_PRODUCT_URL is not set: run make product-e2e");
    if (seed === null) throw new Error("no seed state: run make product-seed first");
  });

  test("the seeded business's obligations, in the list and the calendar, open to one", async ({
    page,
    checkA11y,
  }) => {
    const { tenantId, entityId, registrationId } = seed as SeedState;
    const listed = [
      ...(await obligationsOf(tenantId, entityId)),
      ...(await obligationsOf(tenantId, registrationId)),
    ].sort(byDue);
    expect(
      listed.length,
      "make product-seed decides the seed rules for the business",
    ).toBeGreaterThan(0);

    await signInAsSeededOwner(page, seed as SeedState, `/b/${entityId}`);
    const tabs = page.getByRole("navigation", { name: "Pages of this business" });
    await tabs.getByRole("link", { name: "Obligations", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Obligations" })).toBeVisible();
    const rows = page.locator("tr[data-obligation]");
    await expect(rows).toHaveCount(Math.min(listed.length, 25));
    await expect(rows.first()).toHaveAttribute("data-obligation", listed[0]?.obligation_id ?? "");
    await expect(rows.first()).toContainText(listed[0]?.title ?? "");
    await checkA11y();

    // Still to do: only open and in-progress obligations stay.
    const filters = page.getByRole("form", { name: "Filter the obligations" });
    await filters.getByLabel("Status").selectOption("todo");
    await filters.getByRole("button", { name: "Show" }).click();
    await expect(page).toHaveURL(/\?status=todo$/);
    const open = listed.filter((item) => item.status === "open" || item.status === "in_progress");
    expect(open.length, "the seeded business has obligations still to do").toBeGreaterThan(0);
    await expect(rows).toHaveCount(Math.min(open.length, 25));
    for (const status of await rows.evaluateAll((items) =>
      items.map((item) => item.getAttribute("data-status")),
    )) {
      expect(["open", "in_progress"]).toContain(status);
    }

    // The calendar of the month the first open obligation falls due in.
    const target = open.find((item) => item.due_at !== null) as ListedBody;
    const day = istDay(target.due_at as string);
    await tabs.getByRole("link", { name: "Calendar", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Calendar" })).toBeVisible();
    await page.goto(`/b/${entityId}/calendar?month=${day.slice(0, 7)}`);
    const cell = page.locator(`[role='gridcell'][data-key='${day}']`);
    await expect(cell).toContainText(/obligations? due/);
    await checkA11y();
    await cell.click();
    const chosen = page.locator("[data-slot='calendar-day']");
    await expect(chosen.locator(`li[data-obligation='${target.obligation_id}']`)).toBeVisible();
    await chosen.getByRole("link", { name: target.title }).first().click();
    await expect(page).toHaveURL(new RegExp(`/b/${entityId}/obligations/${target.obligation_id}$`));
    await expect(page.getByRole("heading", { level: 1, name: target.title })).toBeVisible();
  });

  test("an obligation's page: its citations, the synthetic approvers, the not-reviewed warning, why it applies", async ({
    page,
    checkA11y,
  }) => {
    const { tenantId, entityId, registrationId } = seed as SeedState;
    const target = (await obligationsOf(tenantId, registrationId))
      .filter((item) => item.status === "open")
      .sort(byDue)[0] as ListedBody;
    expect(target, "the seeded registration has an open obligation").toBeDefined();
    const detail = await onProduct<DetailBody>(
      tenantId,
      `/v1/obligation/obligations/${target.obligation_id}`,
    );

    await signInAsSeededOwner(
      page,
      seed as SeedState,
      `/b/${entityId}/obligations/${target.obligation_id}`,
    );
    await expect(page.getByRole("heading", { level: 1, name: target.title })).toBeVisible();
    const rule = page.locator("[data-slot='obligation-rule']");
    // The demo publication's approvals are synthetic: the seed rule still needs review.
    expect(detail.rule_version?.seed_status).toBe("needs_review");
    await expect(rule.locator("[data-slot='not-reviewed']")).toContainText("Not yet reviewed");
    for (const approver of SYNTHETIC_APPROVERS) {
      expect(detail.rule_version?.approved_by).toContain(approver);
      await expect(rule.locator(`[data-approver='${approver}']`)).toHaveText(approver);
    }
    expect(detail.citations.length, "the seed rule cites a verified clause").toBeGreaterThan(0);
    const citations = page.locator("[data-slot='citation-list'] > li");
    await expect(citations).toHaveCount(detail.citations.length);
    await expect(citations.first().locator("blockquote")).toHaveText(
      detail.citations[0]?.quote ?? "",
    );
    await citations
      .first()
      .getByText(/^Read the whole clause/)
      .click();
    await expect(citations.first().locator("[data-slot='clause-text']")).toBeVisible();
    const why = page.locator("[data-slot='why-applies']");
    await expect(why).toContainText("Applies");
    await expect(why.getByRole("table")).toBeVisible();
    await expect(page.getByRole("complementary", { name: "Not legal advice" })).toBeVisible();
    await checkA11y();
  });

  test("a new business's first obligation turns up on the summary; it is started, completed through a lost answer, and commented on", async ({
    page,
    checkA11y,
  }) => {
    test.setTimeout(240_000);
    const { tenantId } = seed as SeedState;
    const stamp = new Date().toISOString();
    const name = `Web journey probe ${stamp} (synthetic)`;
    const created = await onProduct<{ business: { id: string } }>(tenantId, "/v1/businesses", {
      method: "POST",
      headers: { "Idempotency-Key": randomUUID() },
      body: JSON.stringify({
        name,
        gstin: probeGstin(),
        registration_name: name,
        answers: PROBE_ANSWERS,
      }),
    });
    const probe = created.business.id;

    await signInAsSeededOwner(page, seed as SeedState, `/onboarding/${probe}/done`);
    const first = page.locator("[data-slot='first-obligation']");
    await expect(
      first.getByRole("heading", { level: 2, name: "Your first obligation" }),
    ).toBeVisible();
    // The worker decides the published rules for the new business and makes its obligations.
    await expect(first).toHaveAttribute("data-phase", "found", { timeout: 120_000 });
    await checkA11y();
    await first.getByRole("link").first().click();
    await expect(page).toHaveURL(new RegExp(`/b/${probe}/obligations/[0-9a-f-]{36}$`));
    const obligationId = new URL(page.url()).pathname.split("/").at(-1) as string;

    const status = page.locator("[data-slot='status-panel']");
    await status.getByRole("button", { name: "Start work" }).click();
    await expect(status.locator("[data-slot='tracking-done']")).toHaveText(
      "Started: the obligation is in progress.",
    );
    await expect(page.getByLabel("The obligation")).toContainText("In progress");

    // The first complete reaches the service, but its answer never reaches the browser; "Try
    // again" sends the same request with the same key, and the service replays its first answer.
    let lost = false;
    await page.route(`**/b/${probe}/obligations/${obligationId}`, async (route) => {
      const request = route.request();
      if (lost || request.method() !== "POST" || request.headers()["next-action"] === undefined) {
        await route.fallback();
        return;
      }
      lost = true;
      await route.fetch();
      await route.abort("connectionreset");
    });
    await status.getByRole("button", { name: "Mark as done" }).click();
    const dialog = page.getByRole("dialog", { name: "Mark this obligation as done?" });
    await dialog.getByRole("button", { name: "Mark as done" }).click();
    await expect(status.getByText("No answer arrived")).toBeVisible();
    await checkA11y();
    await status.getByRole("button", { name: "Try again" }).click();
    await expect(status.locator("[data-slot='tracking-done']")).toHaveText(
      "Marked as done. This request had already been recorded, so nothing was recorded twice.",
    );
    await page.unroute(`**/b/${probe}/obligations/${obligationId}`);
    await expect(page.getByLabel("The obligation")).toContainText("Done");
    const closed = await onProduct<DetailBody>(
      tenantId,
      `/v1/obligation/obligations/${obligationId}`,
    );
    expect(closed.status).toBe("done");
    expect(closed.history.filter((change) => change.kind === "closed")).toHaveLength(1);

    const comment = `Example journey comment ${stamp}`;
    const comments = page.getByRole("form", { name: "Add a comment" });
    await comments.getByLabel(/Comment/).fill(comment);
    await comments.getByRole("button", { name: "Add the comment" }).click();
    await expect(page.locator("[data-slot='comments']")).toContainText(comment);
    const read = await onProduct<DetailBody>(
      tenantId,
      `/v1/obligation/obligations/${obligationId}`,
    );
    expect(read.comments.map((item) => item.body)).toContain(comment);
    await expect(page.locator("[data-slot='history']")).toContainText("Closed: Done");
    await checkA11y();
  });

  test("the annual return's change is in the feed and applies to the seeded business", async ({
    page,
    checkA11y,
  }) => {
    const { tenantId, entityId } = seed as SeedState;
    const feed = await onProduct<{ items: ChangeBody[] }>(tenantId, "/v1/changes?limit=100");
    const annual = feed.items.find((item) => item.rule_key === ANNUAL_RULE);
    expect(
      annual,
      "make product-check (or an earlier check) publishes the annual return",
    ).toBeDefined();
    const impact = await onProduct<{
      items: { entity_id: string; businesses: { result: string }[] }[];
    }>(tenantId, `/v1/changes/${annual?.rule_version_id}/impact?limit=200`);
    const ours = impact.items.find((client) => client.entity_id === entityId);
    expect(ours?.businesses.some((business) => business.result === "applies")).toBe(true);

    await signInAsSeededOwner(page, seed as SeedState, `/b/${entityId}/changes`);
    await expect(page.getByRole("heading", { level: 1, name: "Changes" })).toBeVisible();
    let card = page.locator(`article[data-rule-version='${annual?.rule_version_id}']`).first();
    for (let pages = 0; pages < 5 && (await card.count()) === 0; pages += 1) {
      await page.getByRole("link", { name: "Older changes" }).click();
      card = page.locator(`article[data-rule-version='${annual?.rule_version_id}']`).first();
    }
    await expect(card).toHaveAttribute("data-applicability", "applies");
    await expect(card.locator("[data-slot='applicability']")).toHaveText(
      "Applies to this business",
    );
    await expect(card.locator("[data-slot='not-reviewed']")).toContainText("Not yet reviewed");
    for (const approver of SYNTHETIC_APPROVERS) {
      await expect(card.locator(`[data-approver='${approver}']`)).toHaveCount(1);
    }
    await checkA11y();
  });

  test("asks when the monthly return is due and gets a cited answer", async ({
    page,
    checkA11y,
  }) => {
    const { tenantId, entityId, registrationId } = seed as SeedState;
    await signInAsSeededOwner(page, seed as SeedState, `/b/${entityId}/ask`);
    await expect(page.getByRole("heading", { level: 1, name: "Ask" })).toBeVisible();
    const form = page.getByRole("form", { name: "Ask a question" });
    await expect(form.getByLabel("About")).toHaveValue(registrationId);
    await form.getByLabel(/Your question/).fill(QUESTION);
    await form.getByRole("button", { name: "Ask" }).click();
    const answer = page.locator("[data-slot='answer']");
    await expect(answer).toHaveAttribute("data-outcome", "answered", { timeout: 30_000 });
    await expect(answer.locator("[data-slot='answer-layer']")).toHaveText(
      "Answered from this business's obligations",
    );
    const expected = await onProduct<{ answer: string; citations: unknown[] }>(tenantId, "/v1/qa", {
      method: "POST",
      body: JSON.stringify({ question: QUESTION, business_node_id: registrationId }),
    });
    await expect(answer.locator("[data-slot='answer-text']")).toHaveText(expected.answer);
    expect(expected.citations.length).toBeGreaterThan(0);
    await expect(answer.locator("[data-citation]")).toHaveCount(expected.citations.length);
    await expect(
      answer.getByRole("link", { name: /Open the source document/ }).first(),
    ).toBeVisible();
    await checkA11y();
  });
});
