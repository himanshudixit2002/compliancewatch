import { expectOk, type SeedClients } from "../http.mts";
import { DEMO } from "../lib.mts";

/**
 * The owner's consents on the identity service: one row per purpose the onboarding asks for
 * (terms, privacy notice, profile processing, WhatsApp reminders), recorded from the web
 * onboarding source against the current draft notice version, then read back as states.
 */
export interface ConsentsResult {
  recorded: string[];
  granted: string[];
}

export async function seedConsents(
  clients: SeedClients,
  ownerId: string,
  log: (line: string) => void,
): Promise<ConsentsResult> {
  const step = "consents";
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
          notice_version: DEMO.noticeVersion,
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
