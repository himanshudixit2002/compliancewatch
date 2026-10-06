// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { BUSINESS_DTO, ENTITY_ID } from "@/test/business-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { TENANT_ID, USER_ID } from "@/test/obligation-fixture";
import { getAskPage } from "./queries";

const session: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("getAskPage", () => {
  it("reads the business's nodes and whether asking is on for the tenant", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_QA_ENABLED", "true");
    const fake = fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO }]);
    const page = await getAskPage(session, ENTITY_ID, { fetchImpl: fake.fetchImpl });
    expect(page.ok && page.value).toMatchObject({
      business: { id: ENTITY_ID, name: "Example business" },
      enabled: true,
    });
    expect(page.ok && page.value.nodes).toHaveLength(2);
  });

  it("says asking is off without the flag, and passes on a missing business", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    const off = await getAskPage(session, ENTITY_ID, {
      fetchImpl: fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO }]).fetchImpl,
    });
    expect(off.ok && off.value.enabled).toBe(false);
    const missing = await getAskPage(session, ENTITY_ID, {
      fetchImpl: fakeFetch([{ path: `/v1/businesses/${ENTITY_ID}`, status: 404, problem: {} }])
        .fetchImpl,
    });
    expect(missing.ok ? null : missing.error.kind).toBe("not_found");
  });
});
