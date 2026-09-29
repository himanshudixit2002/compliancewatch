// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { EnvError, loadEnv, resetEnvCache } from "../env";
import { isProblem } from "../result";
import { FakeAuthProvider } from "./fake";
import { PROVIDER_VARIABLE, providerFor } from "./provider";

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("providerFor", () => {
  it("answers the fake adapter in local and test", () => {
    for (const name of ["local", "test"]) {
      const result = providerFor(loadEnv({ CW_WEB_ENV: name, CW_WEB_AUTH_PROVIDER: "fake" }));
      expect(result.ok, name).toBe(true);
      if (!result.ok) return;
      expect(result.value).toBeInstanceOf(FakeAuthProvider);
      expect(result.value.name).toBe("fake");
      expect(result.value.methods).toEqual(["fake"]);
    }
  });

  it("explains an unset provider by naming the variable", () => {
    const result = providerFor(loadEnv({}));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.error.kind).toBe("unavailable");
    expect(isProblem(result.error, "web-auth-provider-missing")).toBe(true);
    expect(result.error.problem?.detail).toContain(PROVIDER_VARIABLE);
    expect(result.error.problem?.detail).toContain("fake (local and test only)");
  });

  it("reserves supabase until its adapter exists", () => {
    const result = providerFor(loadEnv({ CW_WEB_ENV: "prod", CW_WEB_AUTH_PROVIDER: "supabase" }));
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(isProblem(result.error, "web-auth-provider-not-implemented")).toBe(true);
    expect(result.error.problem?.detail).toContain("WP14");
  });

  it("reads the process environment by default", () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
    expect(providerFor().ok).toBe(true);
    resetEnvCache();
    vi.stubEnv("CW_WEB_ENV", "staging");
    expect(() => providerFor()).toThrow(EnvError);
  });
});
