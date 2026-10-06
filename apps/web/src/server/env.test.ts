// @vitest-environment node
import { randomBytes } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SERVICE_NAMES } from "@/shared/config/services";
import {
  AUTH_PROVIDER_NAMES,
  EnvError,
  WEB_ENVS,
  decodeSessionSecret,
  defaultServiceUrl,
  getEnv,
  isLocalOrTest,
  isWebEnvName,
  loadEnv,
  requireSessionSecret,
  resetEnvCache,
  serviceUrl,
  webEnvName,
} from "./env";

const SECRET = randomBytes(32).toString("base64");

afterEach(() => {
  vi.unstubAllEnvs();
  resetEnvCache();
});

describe("loadEnv", () => {
  it("fills every default from an empty record", () => {
    const env = loadEnv({});
    expect(env.CW_WEB_ENV).toBe("local");
    expect(env.CW_WEB_AUTH_PROVIDER).toBeUndefined();
    expect(env.CW_WEB_SESSION_SECRET).toBeUndefined();
    expect(env.CW_WEB_SESSION_TTL_SECONDS).toBe(28_800);
    expect(env.CW_WEB_REQUEST_TIMEOUT_MS).toBe(10_000);
    expect(env.CW_WEB_RULEBOOK_WRITE_TOKEN).toBeUndefined();
    expect(env.CW_WEB_PIPELINE_UPLOAD_MAX_BYTES).toBe(25_000_000);
    expect(env.CW_WEB_RULEBOOK_REVIEW_TOKEN).toBeUndefined();
    expect(env.CW_WEB_ADMIN_IP_ALLOWLIST).toEqual([]);
    expect(env.CW_WEB_TRUST_FORWARDED_IP).toBe(false);
    expect(env.CW_WEB_SEED_STATE_PATH).toBe("../../var/seed/last.json");
    expect(env.CW_WEB_BUILD_SHA).toBeUndefined();
  });

  it("defaults each service URL to the Makefile's port order, identity 8001 to pipeline 8010", () => {
    const env = loadEnv({});
    SERVICE_NAMES.forEach((service, index) => {
      expect(serviceUrl(service, env)).toBe(`http://localhost:${8001 + index}`);
      expect(defaultServiceUrl(service)).toBe(`http://localhost:${8001 + index}`);
    });
    expect(serviceUrl("llm-gateway", env)).toBe("http://localhost:8008");
  });

  it("treats an empty value as unset and ignores variables outside CW_WEB_", () => {
    const env = loadEnv({ CW_WEB_ENV: "", CW_WEB_SESSION_TTL_SECONDS: "", PORT: "3000", X: "y" });
    expect(env.CW_WEB_ENV).toBe("local");
    expect(env.CW_WEB_SESSION_TTL_SECONDS).toBe(28_800);
    expect(Object.keys(env)).not.toContain("PORT");
  });

  it("accepts the four environment names and refuses anything else by name", () => {
    for (const name of WEB_ENVS) expect(loadEnv({ CW_WEB_ENV: name }).CW_WEB_ENV).toBe(name);
    expect(() => loadEnv({ CW_WEB_ENV: "production" })).toThrow(EnvError);
    expect(() => loadEnv({ CW_WEB_ENV: "production" })).toThrow(/CW_WEB_ENV/);
  });

  it("parses URLs, strips a trailing slash and refuses non-http values", () => {
    const env = loadEnv({ CW_WEB_PROFILE_URL: "http://localhost:9202/" });
    expect(env.CW_WEB_PROFILE_URL).toBe("http://localhost:9202");
    expect(serviceUrl("profile", env)).toBe("http://localhost:9202");
    expect(loadEnv({ CW_WEB_QA_URL: "https://qa.internal" }).CW_WEB_QA_URL).toBe(
      "https://qa.internal",
    );
    expect(() => loadEnv({ CW_WEB_IDENTITY_URL: "ftp://x" })).toThrow(/CW_WEB_IDENTITY_URL/);
    expect(() => loadEnv({ CW_WEB_IDENTITY_URL: "not a url" })).toThrow(/CW_WEB_IDENTITY_URL/);
  });

  it("allows the fake provider in local and test only, and reserves supabase everywhere", () => {
    expect(loadEnv({ CW_WEB_AUTH_PROVIDER: "fake" }).CW_WEB_AUTH_PROVIDER).toBe("fake");
    expect(loadEnv({ CW_WEB_ENV: "test", CW_WEB_AUTH_PROVIDER: "fake" }).CW_WEB_AUTH_PROVIDER).toBe(
      "fake",
    );
    for (const name of ["staging", "prod"] as const) {
      expect(() => loadEnv({ CW_WEB_ENV: name, CW_WEB_AUTH_PROVIDER: "fake" })).toThrow(
        /CW_WEB_AUTH_PROVIDER: fake is allowed only when CW_WEB_ENV is local or test/,
      );
      expect(
        loadEnv({ CW_WEB_ENV: name, CW_WEB_AUTH_PROVIDER: "supabase" }).CW_WEB_AUTH_PROVIDER,
      ).toBe("supabase");
    }
    expect(() => loadEnv({ CW_WEB_AUTH_PROVIDER: "keycloak" })).toThrow(/CW_WEB_AUTH_PROVIDER/);
    expect(AUTH_PROVIDER_NAMES).toEqual(["fake", "supabase"]);
  });

  it("requires the session secret to be 32 base64 bytes when set", () => {
    expect(loadEnv({ CW_WEB_SESSION_SECRET: SECRET }).CW_WEB_SESSION_SECRET).toBe(SECRET);
    expect(() => loadEnv({ CW_WEB_SESSION_SECRET: "short" })).toThrow(/CW_WEB_SESSION_SECRET/);
    expect(() => loadEnv({ CW_WEB_SESSION_SECRET: randomBytes(16).toString("base64") })).toThrow(
      /32 random bytes/,
    );
    expect(() => loadEnv({ CW_WEB_SESSION_SECRET: "not base64!!" })).toThrow(EnvError);
  });

  it("bounds the numbers and refuses text", () => {
    expect(loadEnv({ CW_WEB_SESSION_TTL_SECONDS: "3600" }).CW_WEB_SESSION_TTL_SECONDS).toBe(3600);
    expect(() => loadEnv({ CW_WEB_SESSION_TTL_SECONDS: "0" })).toThrow(/CW_WEB_SESSION_TTL/);
    expect(() => loadEnv({ CW_WEB_SESSION_TTL_SECONDS: "90000" })).toThrow(/CW_WEB_SESSION_TTL/);
    expect(() => loadEnv({ CW_WEB_REQUEST_TIMEOUT_MS: "soon" })).toThrow(
      /CW_WEB_REQUEST_TIMEOUT_MS/,
    );
    expect(() => loadEnv({ CW_WEB_REQUEST_TIMEOUT_MS: "1.5" })).toThrow(
      /CW_WEB_REQUEST_TIMEOUT_MS/,
    );
    expect(
      loadEnv({ CW_WEB_PIPELINE_UPLOAD_MAX_BYTES: "1000" }).CW_WEB_PIPELINE_UPLOAD_MAX_BYTES,
    ).toBe(1000);
    expect(() => loadEnv({ CW_WEB_PIPELINE_UPLOAD_MAX_BYTES: "100000001" })).toThrow(
      /CW_WEB_PIPELINE_UPLOAD_MAX_BYTES/,
    );
  });

  it("splits the admin allow-list on commas and checks each entry", () => {
    const env = loadEnv({ CW_WEB_ADMIN_IP_ALLOWLIST: " 10.0.0.0/8, 2001:db8::/32 ,,203.0.113.7" });
    expect(env.CW_WEB_ADMIN_IP_ALLOWLIST).toEqual(["10.0.0.0/8", "2001:db8::/32", "203.0.113.7"]);
    expect(() => loadEnv({ CW_WEB_ADMIN_IP_ALLOWLIST: "office" })).toThrow(
      /CW_WEB_ADMIN_IP_ALLOWLIST/,
    );
  });

  it("reads booleans as true/false or 1/0", () => {
    expect(loadEnv({ CW_WEB_TRUST_FORWARDED_IP: "true" }).CW_WEB_TRUST_FORWARDED_IP).toBe(true);
    expect(loadEnv({ CW_WEB_TRUST_FORWARDED_IP: "1" }).CW_WEB_TRUST_FORWARDED_IP).toBe(true);
    expect(loadEnv({ CW_WEB_TRUST_FORWARDED_IP: "0" }).CW_WEB_TRUST_FORWARDED_IP).toBe(false);
    expect(() => loadEnv({ CW_WEB_TRUST_FORWARDED_IP: "yes" })).toThrow(
      /CW_WEB_TRUST_FORWARDED_IP/,
    );
  });

  it("lists every bad variable in one error", () => {
    expect(() => loadEnv({ CW_WEB_ENV: "dev", CW_WEB_QA_URL: "x" })).toThrow(
      /CW_WEB_ENV.*CW_WEB_QA_URL/,
    );
  });

  it("returns a frozen object", () => {
    const env = loadEnv({ CW_WEB_ADMIN_IP_ALLOWLIST: "10.0.0.0/8" });
    expect(Object.isFrozen(env)).toBe(true);
    expect(Object.isFrozen(env.CW_WEB_ADMIN_IP_ALLOWLIST)).toBe(true);
  });
});

describe("getEnv", () => {
  it("parses process.env once and keeps the result until reset", () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    const first = getEnv();
    expect(first.CW_WEB_ENV).toBe("test");
    vi.stubEnv("CW_WEB_ENV", "staging");
    expect(getEnv()).toBe(first);
    resetEnvCache();
    expect(getEnv().CW_WEB_ENV).toBe("staging");
  });

  it("reports a bad variable at the first call, not at import", () => {
    vi.stubEnv("CW_WEB_ENV", "typo");
    expect(() => getEnv()).toThrow(EnvError);
  });
});

describe("environment helpers", () => {
  it("name the environment and open local-only pages in local and test only", () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    expect(webEnvName()).toBe("test");
    expect(isLocalOrTest()).toBe(true);
    expect(isLocalOrTest("local")).toBe(true);
    expect(isLocalOrTest("staging")).toBe(false);
    expect(isLocalOrTest("prod")).toBe(false);
    expect(webEnvName(loadEnv({ CW_WEB_ENV: "prod" }))).toBe("prod");
    expect(isWebEnvName("staging")).toBe(true);
    expect(isWebEnvName("dev")).toBe(false);
  });

  it("decode the session secret and require it where a session is handled", () => {
    expect(decodeSessionSecret(SECRET)).toHaveLength(32);
    expect(decodeSessionSecret("nope")).toBeNull();
    expect(requireSessionSecret(loadEnv({ CW_WEB_SESSION_SECRET: SECRET }))).toHaveLength(32);
    expect(() => requireSessionSecret(loadEnv({}))).toThrow(
      /CW_WEB_SESSION_SECRET is required to encrypt or decrypt a session/,
    );
    vi.stubEnv("CW_WEB_SESSION_SECRET", SECRET);
    expect(requireSessionSecret()).toEqual(decodeSessionSecret(SECRET));
  });
});
