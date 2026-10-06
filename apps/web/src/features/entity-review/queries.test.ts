// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ClientPrincipal } from "@/server/api/services";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { fakeFetch } from "@/test/fake-fetch";
import { mentionGroupDto, reviewItemDto } from "@/test/rulebook-fixture";
import { QUEUE_PAGE_SIZE } from "./model/queue";
import { getEntityGroup, getEntityQueue } from "./queries";

const analyst: ClientPrincipal = {
  userId: "00000000-0000-5000-8000-0000000000b1",
  tenantId: "00000000-0000-4000-8000-000000000001",
  tenantKind: "internal",
  roles: ["analyst"],
};

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("getEntityQueue", () => {
  it("asks for one group more than a page, to know whether another page follows", async () => {
    const fake = fakeFetch([{ path: "/v1/rulebook/review/entities", body: [mentionGroupDto()] }]);
    const queue = await getEntityQueue(
      { entityType: null, after: null },
      { fetchImpl: fake.fetchImpl },
    );
    expect(fake.requests[0]?.url).toContain(`limit=${QUEUE_PAGE_SIZE + 1}`);
    expect(queue.ok && queue.value.rows.map((row) => row.name)).toEqual(["EXAMPLE-1"]);
    expect(queue.ok && queue.value.nextHref).toBeNull();
  });

  it("passes a failed read on", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/entities", status: 503, problem: { title: "Example outage" } },
    ]);
    const queue = await getEntityQueue(
      { entityType: null, after: null },
      { fetchImpl: fake.fetchImpl },
    );
    expect(!queue.ok && queue.error.message).toBe("Example outage");
  });
});

describe("getEntityGroup", () => {
  it("lists the mentions and offers decisions with the flag on and the review token set", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES", "true");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/entities/items", body: [reviewItemDto()] },
    ]);
    const group = await getEntityGroup(analyst, "form", "EXAMPLE-1", {
      fetchImpl: fake.fetchImpl,
    });
    expect(group.ok && group.value.view.items).toHaveLength(1);
    expect(group.ok && group.value.access).toEqual({ allowed: true });
    // Only the read went out: the access check sends nothing.
    expect(fake.requests).toHaveLength(1);
  });

  it("names the flag that holds the decisions back", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_RULEBOOK_REVIEW_TOKEN", "example-review-token");
    const fake = fakeFetch([{ path: "/v1/rulebook/review/entities/items", body: [] }]);
    const group = await getEntityGroup(analyst, "form", "EXAMPLE-1", {
      fetchImpl: fake.fetchImpl,
    });
    expect(group.ok && group.value.access).toEqual({
      allowed: false,
      title: "The web.admin_rulebook_writes flag is off",
      detail:
        "Turn on the web.admin_rulebook_writes flag for this tenant to send decisions to the rulebook.",
    });
  });

  it("passes a failed read on", async () => {
    const fake = fakeFetch([
      { path: "/v1/rulebook/review/entities/items", status: 422, problem: { title: "Example" } },
    ]);
    const group = await getEntityGroup(analyst, "form", "EXAMPLE-1", {
      fetchImpl: fake.fetchImpl,
    });
    expect(group.ok).toBe(false);
  });
});
