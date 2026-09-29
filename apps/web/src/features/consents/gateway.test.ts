// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { REQUEST_ID_HEADER, TENANT_HEADER } from "@/server/api/client";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { OWNER_ID, grantedState, summaryDto } from "@/test/consent-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { consentsGateway } from "./gateway";

const TENANT = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
const owner: ClientPrincipal = {
  userId: OWNER_ID,
  tenantId: TENANT,
  tenantKind: "business",
  roles: ["owner"],
};
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const NUMBER = "+919800000000";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("ConsentsGateway", () => {
  it("reads the subject's consents from identity, uncached and tenant-scoped", async () => {
    const fake = fakeFetch([
      {
        method: "GET",
        path: "/v1/identity/consents",
        body: summaryDto([grantedState("terms", "terms-of-service@9.9")]),
      },
    ]);
    const result = await consentsGateway({ session: owner, fetchImpl: fake.fetchImpl }).summary(
      OWNER_ID,
    );
    const [request] = fake.requests;
    expect(request?.url).toBe(`http://localhost:8001/v1/identity/consents?subject=${OWNER_ID}`);
    expect(request?.headers[TENANT_HEADER]).toBe(TENANT);
    expect(request?.headers[REQUEST_ID_HEADER]).toMatch(UUID);
    expect(request?.cache).toBe("no-store");
    expect(result.ok && result.value.states[0]?.noticeVersion).toBe("terms-of-service@9.9");
  });

  it("appends one record with the notice version, evidence and recorder", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/identity/consents",
        status: 201,
        body: {
          id: "00000000-0000-4000-8000-000000000c01",
          subject: OWNER_ID,
          purpose: "terms",
          granted: true,
          source: "web_onboarding",
          notice_version: "terms-of-service@9.9",
          evidence: "I accept the terms of service.",
          recorded_by: OWNER_ID,
          recorded_at: "2000-01-01T00:00:00Z",
        },
      },
    ]);
    const result = await consentsGateway({ session: owner, fetchImpl: fake.fetchImpl }).record({
      subject: OWNER_ID,
      purpose: "terms",
      granted: true,
      source: "web_onboarding",
      noticeVersion: "terms-of-service@9.9",
      evidence: "I accept the terms of service.",
      recordedBy: OWNER_ID,
    });
    expect(fake.requests[0]?.method).toBe("POST");
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(TENANT);
    expect(fake.requests[0]?.body).toEqual({
      subject: OWNER_ID,
      purpose: "terms",
      granted: true,
      source: "web_onboarding",
      notice_version: "terms-of-service@9.9",
      evidence: "I accept the terms of service.",
      recorded_by: OWNER_ID,
    });
    expect(result.ok && result.value.recordedAt).toBe("2000-01-01T00:00:00Z");
  });

  it("reports the service's refusal of a grant without a notice version", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/identity/consents",
        status: 422,
        problem: {
          type: "urn:compliancewatch:problem:consent-notice-version-required",
          title: "Notice version required",
        },
      },
    ]);
    const result = await consentsGateway({ session: owner, fetchImpl: fake.fetchImpl }).record({
      subject: OWNER_ID,
      purpose: "terms",
      granted: true,
      source: "web_onboarding",
      noticeVersion: "",
      evidence: "",
      recordedBy: OWNER_ID,
    });
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.message).toBe("Notice version required");
  });

  it("opts a number in on the notification service", async () => {
    const fake = fakeFetch([
      {
        method: "PUT",
        path: `/v1/notification/preferences/whatsapp/${encodeURIComponent(NUMBER)}`,
        body: {
          channel: "whatsapp",
          recipient: NUMBER,
          opted_in: true,
          source: "web_onboarding",
          language: "en",
          quiet_hours_start: "21:00",
          quiet_hours_end: "08:00",
          updated_at: "2000-01-01T00:00:00Z",
        },
      },
    ]);
    const result = await consentsGateway({
      session: owner,
      fetchImpl: fake.fetchImpl,
    }).setPreference("whatsapp", NUMBER, { optedIn: true, source: "web_onboarding" });
    const [request] = fake.requests;
    expect(request?.url).toBe(
      `http://localhost:8006/v1/notification/preferences/whatsapp/${encodeURIComponent(NUMBER)}`,
    );
    expect(request?.method).toBe("PUT");
    expect(request?.body).toEqual({ opted_in: true, source: "web_onboarding" });
    expect(result.ok && result.value.optedIn).toBe(true);
  });
});
