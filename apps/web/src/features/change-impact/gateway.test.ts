// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { IDEMPOTENCY_KEY_HEADER, REPLAYED_HEADER } from "@/server/api/idempotency";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { BUSINESS_DTO } from "@/test/business-fixture";
import { CHANGED_VERSION_ID, changeImpactDto } from "@/test/change-fixture";
import { bulkOutDto } from "@/test/engine-admin-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/obligation-fixture";
import { ruleVersionDetailDto } from "@/test/rule-version-fixture";
import { changeImpactGateway } from "./gateway";

const FIRM = "00000000-0000-4000-8000-00000000c0aa";
const caAdmin: ClientPrincipal = {
  userId: "00000000-0000-4000-8000-00000000c0ab",
  tenantId: FIRM,
  tenantKind: "ca_firm",
  roles: ["ca_admin"],
};
const FORM_UUID = "5d1c8b2e-3f4a-4b6c-8d9e-0f1a2b3c4d5e";

afterEach(() => {
  resetEnvCache();
});

describe("ChangeImpactGateway", () => {
  it("reads the impact for the firm with a result filter, the version without a tenant, and a client", async () => {
    const fake = fakeFetch([
      { path: `/v1/changes/${CHANGED_VERSION_ID}/impact`, body: changeImpactDto() },
      {
        path: `/v1/rulebook/rule-versions/${CHANGED_VERSION_ID}`,
        body: ruleVersionDetailDto({ rule_version_id: CHANGED_VERSION_ID }),
      },
      { path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
    ]);
    const gateway = changeImpactGateway({ session: caAdmin, fetchImpl: fake.fetchImpl });
    const impact = await gateway.impact(CHANGED_VERSION_ID, {
      result: "applies",
      limit: 50,
      cursor: "c1",
    });
    expect(impact.ok && impact.value.clients[0]?.entityId).toBe(ENTITY_ID);
    expect((await gateway.version(CHANGED_VERSION_ID)).ok).toBe(true);
    const business = await gateway.business(ENTITY_ID);
    expect(business.ok && business.value.name).toBe("Example business");
    const [impactRequest, versionRequest, businessRequest] = fake.requests;
    expect(impactRequest?.url).toBe(
      `http://localhost:8004/v1/changes/${CHANGED_VERSION_ID}/impact?limit=50&result=applies&cursor=c1`,
    );
    expect(impactRequest?.headers[TENANT_HEADER]).toBe(FIRM);
    expect(impactRequest?.cache).toBe("no-store");
    expect(versionRequest?.headers[TENANT_HEADER]).toBeUndefined();
    expect(businessRequest?.headers[TENANT_HEADER]).toBe(FIRM);
  });

  it("sends the change card with the form's key and says when the answer was a replay", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/notification/bulk",
        status: 201,
        body: bulkOutDto(),
        headers: { [REPLAYED_HEADER]: "true" },
      },
    ]);
    const sent = await changeImpactGateway({
      session: caAdmin,
      fetchImpl: fake.fetchImpl,
    }).sendChangeCards(CHANGED_VERSION_ID, [REGISTRATION_ID, REGISTRATION_ID], {
      [IDEMPOTENCY_KEY_HEADER]: FORM_UUID,
    });
    if (!sent.ok) throw new Error(sent.error.message);
    expect(sent.value.replayed).toBe(true);
    expect(sent.value.value.queued).toBe(1);
    expect(fake.requests[0]?.body).toEqual({
      rule_version_id: CHANGED_VERSION_ID,
      business_ids: [REGISTRATION_ID],
      kind: "change_card",
    });
    expect(fake.requests[0]?.headers[IDEMPOTENCY_KEY_HEADER.toLowerCase()]).toBe(FORM_UUID);
    expect(fake.requests[0]?.headers[TENANT_HEADER]).toBe(FIRM);
  });

  it("passes the service's refusal on", async () => {
    const fake = fakeFetch([
      {
        method: "POST",
        path: "/v1/notification/bulk",
        status: 503,
        problem: { type: "urn:compliancewatch:problem:notification-bulk-disabled" },
      },
    ]);
    const sent = await changeImpactGateway({
      session: caAdmin,
      fetchImpl: fake.fetchImpl,
    }).sendChangeCards(CHANGED_VERSION_ID, [REGISTRATION_ID], {});
    expect(!sent.ok && sent.error.kind).toBe("unavailable");
  });
});
