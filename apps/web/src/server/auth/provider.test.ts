// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { EnvError, loadEnv, resetEnvCache } from "../env";
import { isProblem } from "../result";
import { FakeAuthProvider } from "./fake";
import { PROVIDER_VARIABLE, providerFailure, providerFailureKind, providerFor } from "./provider";
import { SupabaseAuthProvider } from "./supabase";

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
      expect(result.value.methods).toEqual(["dev", "phone", "email"]);
    }
  });

  it("answers the supabase adapter with its URL and anon key", () => {
    const result = providerFor(
      loadEnv({
        CW_WEB_ENV: "prod",
        CW_WEB_AUTH_PROVIDER: "supabase",
        CW_WEB_SUPABASE_URL: "https://project.supabase.test",
        CW_WEB_SUPABASE_ANON_KEY: "anon-test-value",
      }),
    );
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value).toBeInstanceOf(SupabaseAuthProvider);
    expect(result.value.methods).toEqual(["phone", "email"]);
    expect(result.value.mfaMode).toBe("totp");
    expect(result.value.signInAsPersona).toBeUndefined();
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

  it("reads the process environment by default", () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_AUTH_PROVIDER", "fake");
    expect(providerFor().ok).toBe(true);
    resetEnvCache();
    vi.stubEnv("CW_WEB_ENV", "staging");
    expect(() => providerFor()).toThrow(EnvError);
  });
});

describe("providerFailure", () => {
  it("names the kind in a web-local problem and reads it back", () => {
    const error = providerFailure("rate_limited", "Wait a minute.", { retryAfterSeconds: 60 });
    expect(error.kind).toBe("rate_limited");
    expect(error.status).toBe(429);
    expect(error.problem?.type).toBe("urn:compliancewatch:problem:web-provider-rate-limited");
    expect(error.problem?.detail).toBe("Wait a minute.");
    expect(error.retryAfterSeconds).toBe(60);
    expect(providerFailureKind(error)).toBe("rate_limited");
    expect(providerFailureKind(providerFailure("invalid_code"))).toBe("invalid_code");
    expect(providerFailureKind({ kind: "network", requestId: "", message: "x" })).toBeNull();
    expect(
      providerFailureKind({
        kind: "forbidden",
        requestId: "",
        message: "x",
        problem: {
          type: "urn:compliancewatch:problem:web-provider-nonsense",
          title: "x",
          status: 403,
        },
      }),
    ).toBeNull();
  });
});
