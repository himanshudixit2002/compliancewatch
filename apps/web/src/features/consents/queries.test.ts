// @vitest-environment node
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { ACCEPTED_STATES, OWNER_ID, summaryDto } from "@/test/consent-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { getConsentStep, type ConsentSession } from "./queries";

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
