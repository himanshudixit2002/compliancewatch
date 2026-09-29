// @vitest-environment node
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { seedState, seedStatePath } from "./queries";

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
