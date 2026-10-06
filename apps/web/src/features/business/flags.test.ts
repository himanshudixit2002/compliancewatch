// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { screenById, type Screen } from "@/shared/config/screens";
import { businessFlags, businessPageFlags } from "./flags";

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("businessPageFlags", () => {
  it("names the flags the business pages sit behind, once each", () => {
    expect(businessPageFlags()).toEqual(["web.qa_enabled"]);
    const twice: Screen = { ...screenById("owner.ask"), id: "owner.example-flagged" };
    const elsewhere: Screen = { ...screenById("owner.ask"), id: "owner.x", route: "/settings/x" };
    expect(businessPageFlags([screenById("owner.ask"), twice, elsewhere])).toEqual([
      "web.qa_enabled",
    ]);
  });
});

describe("businessFlags", () => {
  it("answers which of them are on for the tenant", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    expect([
      ...(await businessFlags({ tenantId: "00000000-0000-4000-8000-0000000000aa" })),
    ]).toEqual([]);
    vi.stubEnv("CW_WEB_FLAG_QA_ENABLED", "true");
    resetEnvCache();
    await resetFlagReader();
    expect([
      ...(await businessFlags({ tenantId: "00000000-0000-4000-8000-0000000000aa" })),
    ]).toEqual(["web.qa_enabled"]);
  });
});
