import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { FLAG_NAMES, envVarFor, isFlagName } from "./flags.ts";
import type { FlagName } from "./flags.ts";

const REGISTRY_FILE = join(resolve(__dirname, "../../../../.."), "packages/flags/registry.json");

/** The fields of a registry entry this test reads (packages/flags/registry.schema.json). */
interface RegistryEntry {
  name: string;
  type: string;
  default: boolean | string;
  owner: string;
  description: string;
  removal: string;
  expires: string;
  targeting: string;
  env?: string;
  services: string[];
}

const REGISTRY = (JSON.parse(readFileSync(REGISTRY_FILE, "utf8")) as { flags: RegistryEntry[] })
  .flags;
const WEB_ENTRIES = REGISTRY.filter(
  (entry) => entry.name.startsWith("web.") || entry.services.includes("web"),
);

describe("flags", () => {
  it("names exactly the web flags the shared registry declares, sorted", () => {
    expect(WEB_ENTRIES.map((entry) => entry.name)).toEqual([...FLAG_NAMES]);
    expect([...FLAG_NAMES].sort()).toEqual([...FLAG_NAMES]);
  });

  it("declares every web flag as an off bool the web app reads, with its override variable", () => {
    for (const entry of WEB_ENTRIES) {
      expect(entry.name, entry.name).toMatch(/^web\.[a-z_]+$/);
      expect(entry.type, entry.name).toBe("bool");
      expect(entry.default, entry.name).toBe(false);
      expect(entry.owner.length, entry.name).toBeGreaterThan(0);
      expect(entry.removal.trim().length, entry.name).toBeGreaterThan(10);
      expect(entry.description.trim().length, entry.name).toBeGreaterThan(10);
      expect(entry.services, entry.name).toEqual(["web"]);
      expect(entry.env, entry.name).toBe(envVarFor(entry.name as FlagName));
    }
  });

  it("maps a flag name to its local override variable", () => {
    expect(envVarFor("web.qa_enabled")).toBe("CW_WEB_FLAG_QA_ENABLED");
    expect(envVarFor("web.tenant_header_off")).toBe("CW_WEB_FLAG_TENANT_HEADER_OFF");
    expect(isFlagName("web.qa_enabled")).toBe(true);
    expect(isFlagName("qa_enabled")).toBe(false);
  });
});
