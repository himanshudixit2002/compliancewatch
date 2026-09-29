// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { REQUEST_ID_HEADER, TENANT_HEADER } from "@/server/api/client";
import { IDEMPOTENCY_KEY_HEADER } from "@/server/api/idempotency";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import {
  BUSINESS_CREATED_DTO,
  BUSINESS_DTO,
  DEMO_GSTIN,
  ENTITY_ID,
  LOCATION_DTO,
  LOCATION_ID,
  ONBOARDING_DTO,
  PREFILL_DTO,
  REGISTRATION_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
  SNAPSHOT_DTO,
  TENANT_ID,
  USER_ID,
} from "@/test/business-fixture";
import { fakeFetch, type FakeRoute, type RecordedRequest } from "@/test/fake-fetch";
import { businessGateway } from "./gateway";

const owner: ClientPrincipal = {
  userId: USER_ID,
  tenantId: TENANT_ID,
  tenantKind: "business",
  roles: ["owner"],
};
/** The hidden input's value in a test form: an obviously fake UUID. */
const FORM_UUID = "00000000-0000-4000-8000-00000000000f";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const BASE = "http://localhost:8002";

function gatewayWith(routes: readonly FakeRoute[]) {
  const fake = fakeFetch(routes);
  return { fake, gateway: businessGateway({ session: owner, fetchImpl: fake.fetchImpl }) };
}

/** Every call is tenant-scoped, carries a fresh request id and is never cached. */
function expectTenantCall(request: RecordedRequest | undefined, method: string, url: string) {
  expect(request?.method).toBe(method);
  expect(request?.url).toBe(url);
  expect(request?.headers[TENANT_HEADER]).toBe(TENANT_ID);
  expect(request?.headers[REQUEST_ID_HEADER]).toMatch(UUID);
  expect(request?.next).toBeUndefined();
}

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("business API", () => {
  it("lists the tenant's businesses with the query, the limit and the cursor", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "GET",
        path: "/v1/businesses",
        body: {
          items: [
            {
              id: ENTITY_ID,
              name: "Example business",
              pan: "ABCDE1234F",
              gstins: [DEMO_GSTIN],
              updated_at: "2000-01-04T00:00:00Z",
            },
          ],
          next_cursor: "example-cursor",
        },
      },
    ]);
    const page = await gateway.list({ q: "  example ", limit: 20, cursor: "c1" });
    expectTenantCall(fake.requests[0], "GET", `${BASE}/v1/businesses?q=example&limit=20&cursor=c1`);
    expect(fake.requests[0]?.cache).toBe("no-store");
    expect(page.ok && page.value.nextCursor).toBe("example-cursor");
    expect(page.ok && page.value.items[0]?.gstins).toEqual([DEMO_GSTIN]);
    await gateway.list();
    await gateway.list({ q: " ", cursor: "" });
    expect(fake.requests[1]?.url).toBe(`${BASE}/v1/businesses`);
    expect(fake.requests[2]?.url).toBe(`${BASE}/v1/businesses`);
  });

  it("creates a business with the form's Idempotency-Key", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "POST", path: "/v1/businesses", status: 201, body: BUSINESS_CREATED_DTO },
    ]);
    const result = await gateway.create(
      { name: "Example business", gstin: DEMO_GSTIN },
      { [IDEMPOTENCY_KEY_HEADER]: FORM_UUID },
    );
    expectTenantCall(fake.requests[0], "POST", `${BASE}/v1/businesses`);
    expect(fake.requests[0]?.headers["idempotency-key"]).toBe(FORM_UUID);
    expect(fake.requests[0]?.body).toEqual({ name: "Example business", gstin: DEMO_GSTIN });
    expect(result.ok && result.value.created).toBe(true);
    expect(result.ok && result.value.onboarding.next?.key).toBe("example_flag");
  });

  it("reports the 428 when the form carried no key", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "POST",
        path: "/v1/businesses",
        status: 428,
        problem: {
          type: "urn:compliancewatch:problem:idempotency-key-required",
          title: "Idempotency-Key required",
        },
      },
    ]);
    const result = await gateway.create({ name: "Example business" }, {});
    expect(fake.requests[0]?.headers["idempotency-key"]).toBeUndefined();
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("precondition_required");
  });

  it("reports a conflict while the first request with the key is still running", async () => {
    const { gateway } = gatewayWith([
      {
        method: "POST",
        path: "/v1/businesses",
        status: 409,
        headers: { "retry-after": "2" },
        problem: { title: "Request in progress" },
      },
    ]);
    const result = await gateway.create(
      { name: "Example business" },
      { [IDEMPOTENCY_KEY_HEADER]: FORM_UUID },
    );
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.kind).toBe("conflict");
      expect(result.error.retryAfterSeconds).toBe(2);
    }
  });

  it("reads one business and its onboarding checklist", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "GET", path: `/v1/businesses/${ENTITY_ID}`, body: BUSINESS_DTO },
      { method: "GET", path: `/v1/businesses/${ENTITY_ID}/onboarding`, body: ONBOARDING_DTO },
    ]);
    const business = await gateway.get(ENTITY_ID);
    const onboarding = await gateway.onboarding(ENTITY_ID);
    expectTenantCall(fake.requests[0], "GET", `${BASE}/v1/businesses/${ENTITY_ID}`);
    expectTenantCall(fake.requests[1], "GET", `${BASE}/v1/businesses/${ENTITY_ID}/onboarding`);
    expect(business.ok && business.value.registrations[0]?.key).toBe(DEMO_GSTIN);
    expect(onboarding.ok && onboarding.value.total).toBe(8);
  });

  it("stores answers across the business with a patch, and maps field errors", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "PATCH",
        path: `/v1/businesses/${ENTITY_ID}`,
        body: { ...BUSINESS_DTO, version: 6 },
      },
    ]);
    const result = await gateway.update(ENTITY_ID, {
      changes: [
        { key: "example_band", state: "known", value: "large", asOfFy: "2000-01" },
        { key: "example_flag", state: "unsure", nodeId: REGISTRATION_ID },
      ],
    });
    expectTenantCall(fake.requests[0], "PATCH", `${BASE}/v1/businesses/${ENTITY_ID}`);
    expect(fake.requests[0]?.body).toEqual({
      changes: [
        { key: "example_band", state: "known", value: "large", as_of_fy: "2000-01" },
        { key: "example_flag", state: "unsure", node_id: REGISTRATION_ID },
      ],
    });
    expect(result.ok && result.value.version).toBe(6);

    const refused = gatewayWith([
      {
        method: "PATCH",
        path: `/v1/businesses/${ENTITY_ID}`,
        status: 422,
        problem: {
          type: "urn:compliancewatch:problem:invalid-attribute-value",
          title: "Invalid attribute value",
          errors: [
            { loc: ["body", "changes", 0, "value"], msg: "not an allowed value", type: "value" },
          ],
        },
      },
    ]);
    const invalid = await refused.gateway.update(ENTITY_ID, {
      changes: [{ key: "example_kind", state: "known", value: "third" }],
    });
    expect(invalid.ok).toBe(false);
    if (!invalid.ok) {
      expect(invalid.error.kind).toBe("validation");
      expect(invalid.error.fieldErrors).toEqual({ "changes.0.value": ["not an allowed value"] });
    }
  });

  it("adds a registration with the form's Idempotency-Key", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "POST",
        path: `/v1/businesses/${ENTITY_ID}/registrations`,
        status: 201,
        body: {
          business: BUSINESS_DTO,
          registration: REGISTRATION_DTO,
          created: true,
          prefill: PREFILL_DTO,
        },
      },
    ]);
    const result = await gateway.addRegistration(
      ENTITY_ID,
      { gstin: DEMO_GSTIN, name: "Example registration" },
      { [IDEMPOTENCY_KEY_HEADER]: FORM_UUID },
    );
    expectTenantCall(fake.requests[0], "POST", `${BASE}/v1/businesses/${ENTITY_ID}/registrations`);
    expect(fake.requests[0]?.headers["idempotency-key"]).toBe(FORM_UUID);
    expect(fake.requests[0]?.body).toEqual({ gstin: DEMO_GSTIN, name: "Example registration" });
    expect(result.ok && result.value.prefill.reviewTaskId).toBe(PREFILL_DTO.review_task);
  });

  it("reports a business of another tenant as not found", async () => {
    const { gateway } = gatewayWith([
      {
        method: "GET",
        path: `/v1/businesses/${ENTITY_ID}`,
        status: 404,
        problem: { type: "urn:compliancewatch:problem:business-not-found", title: "Not found" },
      },
    ]);
    const result = await gateway.get(ENTITY_ID);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("not_found");
  });

  it("reports a missing tenant header as unauthenticated", async () => {
    const { gateway } = gatewayWith([
      {
        path: "/v1/businesses",
        status: 401,
        problem: {
          type: "urn:compliancewatch:problem:identity-tenant-required",
          title: "Tenant required",
        },
      },
    ]);
    const result = await gateway.list();
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error.kind).toBe("unauthenticated");
  });
});

describe("profile node routes", () => {
  it("reads a node and adds a location under a registration", async () => {
    const { fake, gateway } = gatewayWith([
      { method: "GET", path: `/v1/profile/nodes/${REGISTRATION_ID}`, body: REGISTRATION_DTO },
      { method: "POST", path: "/v1/profile/locations", status: 201, body: LOCATION_DTO },
    ]);
    const node = await gateway.node(REGISTRATION_ID);
    const location = await gateway.addLocation({
      registrationId: REGISTRATION_ID,
      label: "EX-01",
      name: "Example location",
    });
    expectTenantCall(fake.requests[0], "GET", `${BASE}/v1/profile/nodes/${REGISTRATION_ID}`);
    expectTenantCall(fake.requests[1], "POST", `${BASE}/v1/profile/locations`);
    expect(fake.requests[1]?.body).toEqual({
      registration_id: REGISTRATION_ID,
      label: "EX-01",
      name: "Example location",
    });
    expect(node.ok && node.value.parentId).toBe(ENTITY_ID);
    expect(location.ok && location.value.id).toBe(LOCATION_ID);
    expect(location.ok && location.value.created).toBe(true);
  });

  it("reads a snapshot for a year, or without per-year values", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "GET",
        path: `/v1/profile/nodes/${REGISTRATION_ID}/snapshot`,
        body: SNAPSHOT_DTO,
      },
    ]);
    const withYear = await gateway.snapshot(REGISTRATION_ID, "2000-01");
    await gateway.snapshot(REGISTRATION_ID);
    expectTenantCall(
      fake.requests[0],
      "GET",
      `${BASE}/v1/profile/nodes/${REGISTRATION_ID}/snapshot?fy=2000-01`,
    );
    expect(fake.requests[1]?.url).toBe(`${BASE}/v1/profile/nodes/${REGISTRATION_ID}/snapshot`);
    expect(withYear.ok && withYear.value.lineage).toEqual([ENTITY_ID]);
  });

  it("reads the review tasks a node's answers opened", async () => {
    const { fake, gateway } = gatewayWith([
      {
        method: "GET",
        path: `/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`,
        body: [REVIEW_TASK_DTO],
      },
    ]);
    const tasks = await gateway.reviewTasks(REGISTRATION_ID);
    expectTenantCall(
      fake.requests[0],
      "GET",
      `${BASE}/v1/profile/nodes/${REGISTRATION_ID}/review-tasks`,
    );
    expect(tasks.ok && tasks.value.map((task) => task.reason)).toEqual(["not_applicable"]);
  });
});
