// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "./env";
import { flagEnvironment, flagProviderStatus, isEnabled, resetFlagReader } from "./flags";

afterEach(async () => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  resetEnvCache();
  await resetFlagReader();
});

describe("flagEnvironment", () => {
  const record = {
    CW_WEB_FLAG_ANALYTICS_ENABLED: "true",
    CW_FLAG_WEB_QA_ENABLED: "true",
    CW_FLAG_WEB_QA_ENABLED__TENANTS: "00000000-0000-4000-8000-000000000001",
    CW_FLAGS_PROVIDER: "env",
    CW_WEB_ENV: "prod",
  };

  it("passes every variable through in local and test", () => {
    expect(flagEnvironment(record, "local")).toBe(record);
    expect(flagEnvironment(record, "test")).toBe(record);
  });

  it("drops the web overrides and their tenant lists in staging and prod", () => {
    for (const name of ["staging", "prod"] as const) {
      expect(flagEnvironment(record, name)).toEqual({
        CW_FLAGS_PROVIDER: "env",
        CW_WEB_ENV: "prod",
      });
    }
  });
});

describe("isEnabled", () => {
  it("answers off by default", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    expect(await isEnabled("web.analytics_enabled")).toBe(false);
    expect(
      await isEnabled("web.qa_enabled", { tenantId: "00000000-0000-4000-8000-00000000000a" }),
    ).toBe(false);
  });

  it("honours the override variable in local and test", async () => {
    vi.stubEnv("CW_WEB_ENV", "local");
    vi.stubEnv("CW_WEB_FLAG_ANALYTICS_ENABLED", "true");
    expect(await isEnabled("web.analytics_enabled")).toBe(true);
    expect(await isEnabled("web.otel_enabled")).toBe(false);
  });

  it("ignores the override variable in prod", async () => {
    vi.stubEnv("CW_WEB_ENV", "prod");
    vi.stubEnv("CW_WEB_FLAG_ANALYTICS_ENABLED", "true");
    vi.stubEnv("CW_FLAG_WEB_ANALYTICS_ENABLED", "true");
    expect(await isEnabled("web.analytics_enabled")).toBe(false);
  });

  it("answers off and logs when the provider cannot be configured, then tries again", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_FLAGS_PROVIDER", "unleash");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(await isEnabled("web.analytics_enabled")).toBe(false);
    const line = JSON.parse(String(warn.mock.calls[0]?.[0])) as Record<string, unknown>;
    expect(line).toMatchObject({
      event: "flag_configuration_failed",
      flag: "web.analytics_enabled",
    });
    expect(String(line.error)).toContain("CW_UNLEASH_URL");

    vi.stubEnv("CW_FLAGS_PROVIDER", "env");
    vi.stubEnv("CW_WEB_FLAG_ANALYTICS_ENABLED", "true");
    expect(await isEnabled("web.analytics_enabled")).toBe(true);
  });
});

describe("flagProviderStatus", () => {
  it("names the provider the reader answers through", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    expect(await flagProviderStatus()).toEqual({ ok: true, provider: "env" });
  });

  it("says why the provider could not be configured, then tries again", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_FLAGS_PROVIDER", "unleash");
    const status = await flagProviderStatus();
    expect(status.ok).toBe(false);
    expect(!status.ok && status.reason).toContain("CW_UNLEASH_URL");

    vi.stubEnv("CW_FLAGS_PROVIDER", "env");
    expect(await flagProviderStatus()).toEqual({ ok: true, provider: "env" });
  });
});
