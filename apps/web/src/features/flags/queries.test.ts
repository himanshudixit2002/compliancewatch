// @vitest-environment node
import { REGISTRY, type FlagDefinition } from "@compliancewatch/flags";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resetEnvCache } from "@/server/env";
import { resetFlagReader } from "@/server/flags";
import { FLAG_NAMES, type FlagName } from "@/shared/config/flags";
import { flagConsoleGateway } from "./gateway";
import type { FlagConsolePort } from "./ports";
import { getFlagConsole } from "./queries";

const TENANT = "00000000-0000-4000-8000-0000000000a1";
const NOW = new Date("2000-01-15T06:30:00Z");

const DEFINITIONS: FlagDefinition[] = [
  {
    name: "example.elsewhere",
    type: "bool",
    default: false,
    owner: "platform",
    description: "Example switch read by another service.",
    removal: "When the example is done.",
    expires: "2000-06-30",
    targeting: "none",
    services: ["example-service"],
  },
  {
    name: "web.qa_enabled",
    type: "bool",
    default: false,
    owner: "ai-platform",
    description: "Example web switch.",
    removal: "When the example is done.",
    expires: "2000-06-30",
    targeting: "none",
    services: ["web"],
  },
];

function fakePort(answers: Partial<Record<FlagName, boolean>>, ok = true) {
  const asked: { name: FlagName; tenantId: string }[] = [];
  const port: FlagConsolePort = {
    definitions: () => DEFINITIONS,
    provider: async () => (ok ? { ok: true, provider: "env" } : { ok: false, reason: "no url" }),
    isEnabled: async (name, tenantId) => {
      asked.push({ name, tenantId });
      return answers[name] ?? false;
    },
  };
  return { port, asked };
}

afterEach(async () => {
  vi.unstubAllEnvs();
  resetEnvCache();
  await resetFlagReader();
});

describe("getFlagConsole", () => {
  it("asks the reader about the web app's flags only, for the session's tenant", async () => {
    const { port, asked } = fakePort({ "web.qa_enabled": true });
    const view = await getFlagConsole({ tenantId: TENANT }, { port, now: NOW });
    expect(asked).toEqual([{ name: "web.qa_enabled", tenantId: TENANT }]);
    expect(view.rows.map((row) => row.value.kind)).toEqual(["elsewhere", "on"]);
    expect(view.today).toBe("2000-01-15");
    expect(view.provider).toEqual({ ok: true, provider: "env" });
  });

  it("evaluates nothing when the reader cannot be configured", async () => {
    const { port, asked } = fakePort({ "web.qa_enabled": true }, false);
    const view = await getFlagConsole({ tenantId: TENANT }, { port, now: NOW });
    expect(asked).toEqual([]);
    expect(view.provider).toEqual({ ok: false, reason: "no url" });
    expect(view.rows[1]?.value).toEqual({ kind: "unknown" });
  });

  it("reads the real registry and reader by default", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    vi.stubEnv("CW_WEB_FLAG_QA_ENABLED", "true");
    const view = await getFlagConsole({ tenantId: TENANT });
    expect(view.rows.map((row) => row.name)).toEqual(REGISTRY.flags.map((flag) => flag.name));
    const web = view.rows.filter((row) => row.value.kind !== "elsewhere");
    expect(web.map((row) => row.name).sort()).toEqual([...FLAG_NAMES].sort());
    expect(view.rows.find((row) => row.name === "web.qa_enabled")?.value).toEqual({ kind: "on" });
    expect(view.rows.find((row) => row.name === "web.otel_enabled")?.value).toEqual({
      kind: "off",
    });
  });
});

describe("flagConsoleGateway", () => {
  it("offers the registry, the provider and the reader", async () => {
    vi.stubEnv("CW_WEB_ENV", "test");
    const gateway = flagConsoleGateway();
    expect(gateway.definitions()).toBe(REGISTRY.flags);
    expect(await gateway.provider()).toEqual({ ok: true, provider: "env" });
    expect(await gateway.isEnabled("web.otel_enabled", TENANT)).toBe(false);
  });
});
