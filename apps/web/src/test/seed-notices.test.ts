// @vitest-environment node
import { describe, expect, it } from "vitest";
import { PURPOSE_DOCUMENT, noticeFor } from "@/features/consents/model/purposes";
import { readLegalVersions } from "@/server/legal";
import { CONSENT_DOCUMENTS, DEMO, consentNoticeVersion } from "../../scripts/seed/lib.mts";
import { readConsentDocumentVersions } from "../../scripts/seed/steps/consents.mts";

/**
 * The seed runs in plain Node and cannot import the consent step's model, so it keeps its own
 * copy of the purpose-to-document map and reads docs/legal itself. This holds the two together:
 * a seeded consent carries the notice version the web consent step would record.
 */
describe("the seed's consents", () => {
  it("refer each purpose to the document the consent step refers it to", () => {
    for (const purpose of DEMO.consentPurposes) {
      expect(CONSENT_DOCUMENTS[purpose]).toBe(PURPOSE_DOCUMENT[purpose]);
    }
  });

  it("carry the notice version the consent step records", async () => {
    const seeded = await readConsentDocumentVersions();
    const versions = readLegalVersions();
    for (const purpose of DEMO.consentPurposes) {
      expect(consentNoticeVersion(purpose, seeded)).toBe(noticeFor(purpose, versions));
    }
  });
});
