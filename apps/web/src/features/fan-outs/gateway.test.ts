// @vitest-environment node
import { afterEach, describe, expect, it } from "vitest";
import { TENANT_HEADER } from "@/server/api/client";
import { resetEnvCache } from "@/server/env";
import { RUN_VERSION_ID, fanOutRunDto, heldDto, holdDto } from "@/test/engine-admin-fixture";
import { fakeFetch } from "@/test/fake-fetch";
import { ruleVersionDetailDto } from "@/test/rule-version-fixture";
import { fanOutsGateway } from "./gateway";

const ENGINE = "http://localhost:8004/v1/applicability-engine";
const RUN = `/v1/applicability-engine/fan-outs/${RUN_VERSION_ID}`;

afterEach(() => {
  resetEnvCache();
});

describe("FanOutsGateway", () => {
  it("reads the runs, one run and the hold with no tenant header and nothing cached", async () => {
    const fake = fakeFetch([
      {
        path: "/v1/applicability-engine/fan-outs",
        body: { items: [fanOutRunDto()], next_cursor: "next-1" },
      },
      { path: RUN, body: fanOutRunDto({ status: "held" }) },
      { path: "/v1/applicability-engine/fan-out-hold", body: holdDto() },
    ]);
    const gateway = fanOutsGateway({ fetchImpl: fake.fetchImpl });
    const page = await gateway.list({ limit: 25, cursor: "after-1" });
    expect(page.ok && page.value.items[0]?.ruleKey).toBe("example_rule");
    expect(page.ok && page.value.nextCursor).toBe("next-1");
    const run = await gateway.get(RUN_VERSION_ID);
    expect(run.ok && run.value.status).toBe("held");
    const hold = await gateway.hold();
    expect(hold.ok && hold.value.held).toBe(false);
    expect(fake.requests.map((request) => request.url)).toEqual([
      `${ENGINE}/fan-outs?limit=25&cursor=after-1`,
      `${ENGINE}/fan-outs/${RUN_VERSION_ID}`,
      `${ENGINE}/fan-out-hold`,
    ]);
    for (const request of fake.requests) {
      expect(request.headers[TENANT_HEADER]).toBeUndefined();
      expect(request.cache).toBe("no-store");
    }
  });

  it("sets and releases the hold and sends each control with its reason", async () => {
    const fake = fakeFetch([
      { method: "PUT", path: "/v1/applicability-engine/fan-out-hold", body: heldDto() },
      { method: "POST", path: `${RUN}/pause`, body: fanOutRunDto({ status: "paused" }) },
      { method: "POST", path: `${RUN}/resume`, body: fanOutRunDto() },
      { method: "POST", path: `${RUN}/cancel`, body: fanOutRunDto({ status: "cancelled" }) },
    ]);
    const gateway = fanOutsGateway({ fetchImpl: fake.fetchImpl });
    const held = await gateway.setHold(true, "Example deploy in progress");
    expect(held.ok && held.value.held).toBe(true);
    expect((await gateway.pause(RUN_VERSION_ID, "Example pause reason")).ok).toBe(true);
    expect((await gateway.resume(RUN_VERSION_ID, "")).ok).toBe(true);
    const cancelled = await gateway.cancel(RUN_VERSION_ID, "Example cancel reason");
    expect(cancelled.ok && cancelled.value.status).toBe("cancelled");
    expect(
      fake.requests.map((request) => [request.method, request.pathname, request.body]),
    ).toEqual([
      [
        "PUT",
        "/v1/applicability-engine/fan-out-hold",
        { held: true, reason: "Example deploy in progress" },
      ],
      ["POST", `${RUN}/pause`, { reason: "Example pause reason" }],
      ["POST", `${RUN}/resume`, { reason: "" }],
      ["POST", `${RUN}/cancel`, { reason: "Example cancel reason" }],
    ]);
    for (const request of fake.requests) expect(request.headers[TENANT_HEADER]).toBeUndefined();
  });

  it("reads the version from the rulebook, uncached, and passes a refusal on", async () => {
    const fake = fakeFetch([
      {
        path: `/v1/rulebook/rule-versions/${RUN_VERSION_ID}`,
        body: ruleVersionDetailDto({ rule_version_id: RUN_VERSION_ID, status: "published" }),
      },
      {
        method: "POST",
        path: `${RUN}/pause`,
        status: 409,
        problem: { type: "urn:compliancewatch:problem:applicability-fan-out-state" },
      },
    ]);
    const gateway = fanOutsGateway({ fetchImpl: fake.fetchImpl });
    const version = await gateway.version(RUN_VERSION_ID);
    expect(version.ok && version.value.status).toBe("published");
    expect(fake.requests[0]?.url).toBe(
      `http://localhost:8003/v1/rulebook/rule-versions/${RUN_VERSION_ID}`,
    );
    expect(fake.requests[0]?.cache).toBe("no-store");
    const refused = await gateway.pause(RUN_VERSION_ID, "Example pause reason");
    expect(refused.ok).toBe(false);
    expect(!refused.ok && refused.error.kind).toBe("conflict");
  });
});
