import { readFile } from "node:fs/promises";
import { expectOk, type SeedClients } from "../http.mts";
import {
  CONSENT_DOCUMENT_NAMES,
  DEMO,
  consentNoticeVersion,
  legalVersion,
  type ConsentDocument,
} from "../lib.mts";

/**
 * The owner's consents on the identity service: one row per purpose the onboarding asks for
 * (terms, privacy notice, profile processing, WhatsApp reminders), recorded from the web
 * onboarding source, then read back as states. Each carries its document's current Version line
 * from docs/legal as `<document>@<version>`, the notice version the web consent step records.
 */
export interface ConsentsResult {
  recorded: string[];
  granted: string[];
}

/** docs/legal at the repository root, wherever the seed is run from. */
const LEGAL_DIR = new URL("../../../../../docs/legal/", import.meta.url);

/** The Version line of each document the seeded consents refer to. */
export async function readConsentDocumentVersions(
  dir: URL = LEGAL_DIR,
): Promise<Record<ConsentDocument, string>> {
  const versions = {} as Record<ConsentDocument, string>;
  for (const document of CONSENT_DOCUMENT_NAMES) {
    versions[document] = legalVersion(await readFile(new URL(`${document}.md`, dir), "utf8"));
  }
  return versions;
}

export async function seedConsents(
  clients: SeedClients,
  ownerId: string,
  log: (line: string) => void,
): Promise<ConsentsResult> {
  const step = "consents";
  const versions = await readConsentDocumentVersions();
  const recorded: string[] = [];
  for (const purpose of DEMO.consentPurposes) {
    await expectOk(
      step,
      `POST /v1/identity/consents (${purpose})`,
      clients.identity.POST("/v1/identity/consents", {
        body: {
          subject: ownerId,
          purpose,
          source: DEMO.consentSource,
          notice_version: consentNoticeVersion(purpose, versions),
          evidence: DEMO.consentEvidence,
          recorded_by: ownerId,
          granted: true,
        },
      }),
    );
    recorded.push(purpose);
  }
  const summary = await expectOk(
    step,
    "GET /v1/identity/consents?subject=",
    clients.identity.GET("/v1/identity/consents", { params: { query: { subject: ownerId } } }),
  );
  const granted = summary.data.states
    .filter((state) => state.granted)
    .map((state) => state.purpose);
  log(`consents: ${recorded.length} recorded, ${granted.length} granted (${granted.join(", ")})`);
  return { recorded, granted };
}
