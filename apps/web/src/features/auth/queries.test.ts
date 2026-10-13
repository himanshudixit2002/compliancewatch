// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadEnv, resetEnvCache } from "@/server/env";
import { callbackUrl, seedState, seedStatePath } from "./queries";

const incoming = new Headers();

vi.mock("next/headers", () => ({ headers: () => Promise.resolve(incoming) }));

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "web-seed-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
  vi.unstubAllEnvs();
  resetEnvCache();
});

function useSeedFile(name: string, content: string): void {
  const path = join(dir, name);
  writeFileSync(path, content);
  vi.stubEnv("CW_WEB_SEED_STATE_PATH", path);
  resetEnvCache();
}

describe("seedState", () => {
  it("resolves the path against the working directory by default", () => {
    expect(seedStatePath()).toBe(join(process.cwd(), "../../var/seed/last.json"));
  });

  it("reads the last seeded tenant", async () => {
    useSeedFile(
      "last.json",
      JSON.stringify({
        tenant_id: "00000000-0000-4000-8000-000000000002",
        owner_id: "00000000-0000-4000-8000-000000000001",
        seeded_at: "2026-09-29T10:00:00Z",
      }),
    );
    expect(await seedState()).toEqual({
      tenantId: "00000000-0000-4000-8000-000000000002",
      seededAt: "2026-09-29T10:00:00Z",
    });
  });

  it("answers null for a missing, malformed or non-uuid file", async () => {
    vi.stubEnv("CW_WEB_SEED_STATE_PATH", join(dir, "missing.json"));
    resetEnvCache();
    expect(await seedState()).toBeNull();
    useSeedFile("broken.json", "{not json");
    expect(await seedState()).toBeNull();
    useSeedFile("wrong.json", JSON.stringify({ tenant_id: "tenant-1" }));
    expect(await seedState()).toBeNull();
    useSeedFile("bare.json", JSON.stringify({ tenant_id: "00000000-0000-4000-8000-000000000002" }));
    expect(await seedState()).toEqual({ tenantId: "00000000-0000-4000-8000-000000000002" });
  });
});

describe("callbackUrl", () => {
  const supabase = loadEnv({
    CW_WEB_ENV: "prod",
    CW_WEB_AUTH_PROVIDER: "supabase",
    CW_WEB_SUPABASE_URL: "https://project.supabase.test",
    CW_WEB_SUPABASE_ANON_KEY: "anon-test-value",
    CW_WEB_PUBLIC_URL: "https://app.example.test",
    CW_WEB_TRUST_FORWARDED_IP: "true",
  });
  const fake = loadEnv({ CW_WEB_ENV: "test", CW_WEB_AUTH_PROVIDER: "fake" });

  beforeEach(() => {
    for (const name of [...incoming.keys()]) incoming.delete(name);
  });

  it("builds the supabase link's return address from the public URL, never from a header", async () => {
    incoming.set("host", "attacker.example");
    incoming.set("x-forwarded-host", "attacker.example");
    incoming.set("x-forwarded-proto", "http");
    expect(await callbackUrl("/settings/team", supabase)).toBe(
      "https://app.example.test/auth/callback?next=%2Fsettings%2Fteam",
    );
    expect(await callbackUrl(undefined, supabase)).toBe(
      "https://app.example.test/auth/callback?next=",
    );
  });

  it("takes the host the browser asked for with the fake adapter, which sends nothing", async () => {
    incoming.set("host", "app.example.test:3510");
    expect(await callbackUrl("/account", fake)).toBe(
      "https://app.example.test:3510/auth/callback?next=%2Faccount",
    );
    expect(await callbackUrl(undefined, { ...fake, CW_WEB_ENV: "local" })).toBe(
      "http://app.example.test:3510/auth/callback?next=",
    );
    incoming.set("x-forwarded-host", "other.example.test");
    incoming.set("x-forwarded-proto", "https");
    expect(await callbackUrl("", { ...fake, CW_WEB_ENV: "local" })).toBe(
      "http://app.example.test:3510/auth/callback?next=",
    );
    expect(
      await callbackUrl("", { ...fake, CW_WEB_ENV: "local", CW_WEB_TRUST_FORWARDED_IP: true }),
    ).toBe("https://other.example.test/auth/callback?next=");
    for (const name of [...incoming.keys()]) incoming.delete(name);
    expect(await callbackUrl("", fake)).toBe("https://localhost/auth/callback?next=");
  });
});
