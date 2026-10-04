import type { FlagDefinition } from "@compliancewatch/flags";
import { describe, expect, it } from "vitest";
import {
  EXPIRY_WARNING_DAYS,
  expiryOf,
  flagConsoleView,
  flagRows,
  flagSummary,
  isReadByWeb,
} from "./flags";

function definition(overrides: Partial<FlagDefinition> & { name: string }): FlagDefinition {
  return {
    type: "bool",
    default: false,
    owner: "platform",
    description: "Example switch.",
    removal: "When the example is done.",
    expires: "2000-12-31",
    targeting: "none",
    services: ["example-service"],
    ...overrides,
  };
}

const TODAY = "2000-01-15";

const DEFINITIONS: FlagDefinition[] = [
  definition({
    name: "example.choice",
    type: "string",
    default: "first",
    values: ["first", "second"],
    env: "CW_EXAMPLE_CHOICE",
    expires: "2000-01-20",
  }),
  definition({
    name: "example.targeted",
    targeting: "tenant",
    tenants_env: "CW_EXAMPLE_TENANTS",
    owner: "core-product",
    expires: "2000-01-10",
  }),
  definition({ name: "web.example_on", services: ["web"], env: "CW_WEB_FLAG_EXAMPLE_ON" }),
  definition({ name: "web.example_off", services: ["web", "example-service"] }),
];

describe("expiryOf", () => {
  it("is expired once the date has passed, soon within the warning window, later after it", () => {
    expect(expiryOf("2000-01-14", TODAY)).toEqual({ state: "expired", days: -1 });
    expect(expiryOf(TODAY, TODAY)).toEqual({ state: "soon", days: 0 });
    expect(expiryOf("2000-02-14", TODAY)).toEqual({ state: "soon", days: EXPIRY_WARNING_DAYS });
    expect(expiryOf("2000-02-15", TODAY)).toEqual({ state: "later", days: 31 });
  });
});

describe("isReadByWeb", () => {
  it("is true for a flag the web app reads", () => {
    expect(isReadByWeb({ services: ["web"] })).toBe(true);
    expect(isReadByWeb({ services: ["example-service", "web"] })).toBe(true);
    expect(isReadByWeb({ services: ["example-service"] })).toBe(false);
  });
});

describe("flagRows", () => {
  it("keeps the registry's order and wording and the reader's answer for web flags", () => {
    const rows = flagRows(
      DEFINITIONS,
      new Map([
        ["web.example_on", true],
        ["web.example_off", false],
      ]),
      TODAY,
    );
    expect(rows.map((row) => row.name)).toEqual(DEFINITIONS.map((entry) => entry.name));
    expect(rows[0]).toEqual({
      name: "example.choice",
      type: "string",
      defaultValue: "first",
      values: ["first", "second"],
      owner: "platform",
      description: "Example switch.",
      removal: "When the example is done.",
      expires: "2000-01-20",
      expiry: { state: "soon", days: 5 },
      targeting: "none",
      env: "CW_EXAMPLE_CHOICE",
      tenantsEnv: null,
      services: ["example-service"],
      value: { kind: "elsewhere", services: ["example-service"] },
    });
    expect(rows[1]).toMatchObject({
      targeting: "tenant",
      tenantsEnv: "CW_EXAMPLE_TENANTS",
      env: null,
      values: [],
      expiry: { state: "expired", days: -5 },
    });
    expect(rows[2]?.value).toEqual({ kind: "on" });
    expect(rows[3]?.value).toEqual({ kind: "off" });
  });

  it("marks a web flag unknown when the reader gave no answer", () => {
    const rows = flagRows(DEFINITIONS, null, TODAY);
    expect(rows.map((row) => row.value.kind)).toEqual([
      "elsewhere",
      "elsewhere",
      "unknown",
      "unknown",
    ]);
    expect(flagRows(DEFINITIONS, new Map(), TODAY)[2]?.value).toEqual({ kind: "unknown" });
  });
});

describe("flagSummary", () => {
  it("counts the flags, the web flags on, and those near or past their expiry", () => {
    const rows = flagRows(DEFINITIONS, new Map([["web.example_on", true]]), TODAY);
    expect(flagSummary(rows)).toEqual({
      total: 4,
      web: 2,
      webOn: 1,
      expiringSoon: 1,
      expired: 1,
    });
    expect(flagSummary([])).toEqual({ total: 0, web: 0, webOn: 0, expiringSoon: 0, expired: 0 });
  });
});

describe("flagConsoleView", () => {
  it("evaluates nothing when the reader could not be configured", () => {
    const view = flagConsoleView(
      DEFINITIONS,
      { ok: false, reason: "Example reason" },
      new Map([["web.example_on", true]]),
      TODAY,
    );
    expect(view.rows[2]?.value).toEqual({ kind: "unknown" });
    expect(view.summary.webOn).toBe(0);
    expect(view.today).toBe(TODAY);
  });

  it("keeps the reader's answers when it could", () => {
    const view = flagConsoleView(
      DEFINITIONS,
      { ok: true, provider: "env" },
      new Map([["web.example_on", true]]),
      TODAY,
    );
    expect(view.provider).toEqual({ ok: true, provider: "env" });
    expect(view.summary.webOn).toBe(1);
  });
});
