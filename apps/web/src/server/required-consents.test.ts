// @vitest-environment node
import { describe, expect, it } from "vitest";
import { consentSummaryFromDto } from "@/entities/consent/mappers";
import { TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import {
  ACCEPTED_STATES,
  OWNER_ID,
  VERSIONS,
  grantedState,
  summaryDto,
} from "@/test/consent-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import {
  REQUIRED_CONSENTS,
  hasRequiredConsents,
  readConsentSummary,
  requiredConsentsGranted,
} from "./required-consents";

const TENANT = "00000000-0000-4000-8000-00000000000a";
const owner: ClientPrincipal = {
  userId: OWNER_ID,
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};

function identity(states = ACCEPTED_STATES) {
  return fakeFetch([{ method: "GET", path: "/v1/identity/consents", body: summaryDto(states) }]);
}

describe("requiredConsentsGranted", () => {
  it("holds when the terms, the privacy notice and profile processing are granted now", () => {
    expect(REQUIRED_CONSENTS).toEqual(["terms", "privacy_notice", "profile_processing"]);
    expect(
      requiredConsentsGranted(consentSummaryFromDto(summaryDto(ACCEPTED_STATES)), VERSIONS),
    ).toBe(true);
  });

  it("fails for a missing, withdrawn or older grant, and ignores the optional purposes", () => {
    const summary = (states: Parameters<typeof summaryDto>[0]) =>
      consentSummaryFromDto(summaryDto(states));
    expect(requiredConsentsGranted(summary([]), VERSIONS)).toBe(false);
    expect(
      requiredConsentsGranted(
        summary([
          grantedState("terms", "terms-of-service@9.9"),
          grantedState("privacy_notice", "privacy-notice@9.9-draft"),
          grantedState("analytics", "privacy-notice@9.9-draft"),
        ]),
        VERSIONS,
      ),
    ).toBe(false);
    expect(
      requiredConsentsGranted(
        summary([
          grantedState("terms", "terms-of-service@9.9"),
          grantedState("privacy_notice", "privacy-notice@9.9-draft"),
          grantedState("profile_processing", "privacy-notice@9.9-draft", false),
        ]),
        VERSIONS,
      ),
    ).toBe(false);
    expect(
      requiredConsentsGranted(
        summary([
          grantedState("terms", "terms-of-service@9.0"),
          grantedState("privacy_notice", "privacy-notice@9.9-draft"),
          grantedState("profile_processing", "privacy-notice@9.9-draft"),
        ]),
        VERSIONS,
      ),
    ).toBe(false);
  });
});

describe("hasRequiredConsents", () => {
  it("reads the person's records with the tenant header and answers from them", async () => {
    const fake = identity();
    const result = await hasRequiredConsents(owner, {
      fetchImpl: fake.fetchImpl,
      versions: VERSIONS,
    });
    expect(result).toMatchObject({ ok: true, value: true });
    expect(fake.requests).toHaveLength(1);
    const [request] = fake.requests;
    expect(request?.pathname).toBe("/v1/identity/consents");
    expect(new URL(request?.url as string).searchParams.get("subject")).toBe(OWNER_ID);
    expect(request?.headers[TENANT_HEADER]).toBe(TENANT);
    expect(request?.cache).toBe("no-store");

    const none = await hasRequiredConsents(owner, {
      fetchImpl: identity([]).fetchImpl,
      versions: VERSIONS,
    });
    expect(none).toMatchObject({ ok: true, value: false });
  });

  it("passes on the identity service's problem", async () => {
    const fake = fakeFetch([
      { method: "GET", path: "/v1/identity/consents", status: 503, problem: { title: "Down" } },
    ]);
    const result = await hasRequiredConsents(owner, {
      fetchImpl: fake.fetchImpl,
      versions: VERSIONS,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unavailable");
    expect((await readConsentSummary(owner, fake.fetchImpl)).ok).toBe(false);
  });
});
