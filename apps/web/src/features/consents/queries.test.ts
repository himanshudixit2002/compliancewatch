// @vitest-environment node
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { rememberRecipient } from "@/server/remembered-recipients";
import { ACCEPTED_STATES, OWNER_ID, recordDto, summaryDto } from "@/test/consent-fixture";
import { fakeCookies } from "@/test/fake-cookies";
import { fakeFetch } from "@/test/fake-fetch";
import { getConsentSettings, getConsentStep, type ConsentSession } from "./queries";

vi.mock("next/headers", async () => (await import("@/test/fake-cookies")).nextHeadersMock());

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const owner: ConsentSession = {
  userId: OWNER_ID,
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};

/** A docs/legal with the fixture's versions, so the test does not follow the real drafts. */
function legalDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "cw-legal-"));
  writeFileSync(join(dir, "README.md"), "# legal\n");
  const docs = [
    ["privacy-notice", "Privacy notice", "9.9-draft"],
    ["terms-of-service", "Terms of service", "9.9"],
    ["whatsapp-consent", "WhatsApp consent", "9.8-draft"],
  ];
  for (const [name, title, version] of docs) {
    writeFileSync(join(dir, `${name}.md`), `# ${title}\n\nVersion: ${version}\n\nExample text.\n`);
  }
  return dir;
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("getConsentStep", () => {
  it("reads the user's consents and the documents' versions into the step's view", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/identity/consents", body: summaryDto(ACCEPTED_STATES) },
    ]);
    const result = await getConsentStep(owner, { fetchImpl: fake.fetchImpl, legalDir: legalDir() });
    expect(fake.requests[0]?.url).toContain(`subject=${OWNER_ID}`);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.accepted).toBe(true);
    expect(result.value.drafts.map((document) => document.name)).toEqual([
      "privacy-notice",
      "whatsapp-consent",
    ]);
  });

  it("passes the service's failure through", async () => {
    const fake = fakeFetch([
      { path: "/v1/identity/consents", status: 503, problem: { title: "Identity is down" } },
    ]);
    const result = await getConsentStep(owner, { fetchImpl: fake.fetchImpl, legalDir: legalDir() });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatchObject({ kind: "unavailable" });
  });

  it("reads the repository's docs/legal by default", async () => {
    const fake = fakeFetch([{ path: "/v1/identity/consents", body: summaryDto() }]);
    const result = await getConsentStep(owner, { fetchImpl: fake.fetchImpl });
    expect(result.ok && result.value.options[0]?.noticeVersion).toMatch(/^terms-of-service@/);
  });
});

describe("getConsentSettings", () => {
  it("reads the records and fills the dialogs with the number this device remembers", async () => {
    fakeCookies.reset();
    vi.stubEnv("CW_WEB_SESSION_SECRET", Buffer.from(randomBytes(32)).toString("base64"));
    await rememberRecipient(OWNER_ID, "whatsapp", "910000000000");
    const fake = fakeFetch([
      {
        method: "GET",
        path: "/v1/identity/consents",
        body: summaryDto(ACCEPTED_STATES, [recordDto("terms", true, "terms-of-service@9.9")]),
      },
    ]);
    const result = await getConsentSettings(owner, {
      fetchImpl: fake.fetchImpl,
      legalDir: legalDir(),
    });
    expect(fake.requests[0]?.headers["x-tenant-id"]).toBe(TENANT);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.whatsappNumber).toBe("+910000000000");
    expect(result.value.rows[0]).toMatchObject({ purpose: "terms", status: "granted" });
    expect(result.value.history).toHaveLength(1);
  });

  it("passes a failed read on and leaves the number empty when none is remembered", async () => {
    fakeCookies.reset();
    const failed = await getConsentSettings(owner, {
      fetchImpl: fakeFetch([{ path: "/v1/identity/consents", status: 503, problem: {} }]).fetchImpl,
      legalDir: legalDir(),
    });
    expect(failed.ok).toBe(false);
    const empty = await getConsentSettings(owner, {
      fetchImpl: fakeFetch([{ path: "/v1/identity/consents", body: summaryDto() }]).fetchImpl,
      legalDir: legalDir(),
    });
    expect(empty.ok && empty.value.whatsappNumber).toBe("");
  });
});
