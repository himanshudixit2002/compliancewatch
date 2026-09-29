import {
  OpenFeature,
  ParseError,
  TypeMismatchError,
  type EvaluationContext,
} from "@openfeature/server-sdk";
import { PayloadType, type Context as UnleashContext, type Variant } from "unleash-client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  FlagRegistry,
  REGISTRY,
  UnknownFlagError,
  overrideEnv,
  tenantsOverrideEnv,
  type FlagDefinition,
} from "./index.ts";
import {
  DOMAIN,
  EnvProvider,
  UnleashProvider,
  canonicalTenant,
  configureFlags,
  createUnleashClient,
  flagValue,
  isEnabled,
  resetFlags,
  type Environment,
  type UnleashClient,
} from "./server.ts";

const TENANT_A = "3f1c2a8e-0000-4000-8000-00000000000a";
const TENANT_B = "3f1c2a8e-0000-4000-8000-00000000000b";
// Placeholder connection values for the Unleash client; nothing is contacted.
const UNLEASH_URL = "http://unleash.test/api";
const UNLEASH_CLIENT_TOKEN = "default:development.unit-test-placeholder";

function flag(name: string, fields: Partial<FlagDefinition> = {}): FlagDefinition {
  return {
    name,
    type: "bool",
    default: false,
    owner: "platform",
    description: "A demo switch.",
    removal: "Once the demo ships.",
    expires: "2027-03-31",
    targeting: "none",
    services: ["flags"],
    ...fields,
  };
}

const TEST_REGISTRY = new FlagRegistry([
  flag("demo.switch", { env: "CW_DEMO_ENABLED" }),
  flag("demo.tenanted", {
    env: "CW_DEMO_TENANTED_ENABLED",
    targeting: "tenant",
    tenants_env: "CW_DEMO_TENANTS",
  }),
  flag("demo.fresh", { targeting: "tenant" }),
  flag("demo.provider", {
    type: "string",
    default: "none",
    values: ["none", "sandbox"],
    env: "CW_DEMO_PROVIDER",
  }),
]);

let lines: string[] = [];
const log = (line: string): void => {
  lines.push(line);
};
const logged = (): Record<string, unknown>[] =>
  lines.map((line) => JSON.parse(line) as Record<string, unknown>);

async function useEnv(env: Environment): Promise<void> {
  await configureFlags(env, { registry: TEST_REGISTRY, log });
}

beforeEach(async () => {
  lines = [];
  await resetFlags();
});

afterEach(async () => {
  await resetFlags();
});

describe("the registry", () => {
  it("holds every flag in registry.json with its owner and removal", () => {
    const kag = REGISTRY.get("qa.kag");
    expect(kag.env).toBe("CW_QA_KAG_ENABLED");
    expect(kag.tenants_env).toBe("CW_QA_KAG_TENANTS");
    expect(kag.targeting).toBe("tenant");
    for (const definition of REGISTRY.flags) {
      expect(definition.removal).not.toBe("");
      if (definition.type === "bool") expect(definition.default).toBe(false);
    }
  });

  it("throws on a flag it does not hold", () => {
    expect(() => REGISTRY.get("demo.nowhere")).toThrow(UnknownFlagError);
    expect(REGISTRY.has("demo.nowhere")).toBe(false);
    try {
      REGISTRY.get("demo.nowhere");
    } catch (error) {
      expect((error as UnknownFlagError).flag).toBe("demo.nowhere");
      expect((error as UnknownFlagError).name).toBe("UnknownFlagError");
    }
  });

  it("names the override variables after the flag", () => {
    expect(overrideEnv("profile.gstin_category_prefill")).toBe(
      "CW_FLAG_PROFILE_GSTIN_CATEGORY_PREFILL",
    );
    expect(tenantsOverrideEnv("demo.fresh")).toBe("CW_FLAG_DEMO_FRESH__TENANTS");
  });
});

describe("tenant ids", () => {
  it("are canonical: lower case and hyphenated", () => {
    expect(canonicalTenant(` ${TENANT_A.toUpperCase()} `)).toBe(TENANT_A);
    expect(canonicalTenant(TENANT_A.replaceAll("-", ""))).toBe(TENANT_A);
    expect(() => canonicalTenant("acme")).toThrow(ParseError);
  });
});

describe("after resetFlags", () => {
  it("answers every flag's default and logs nothing", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    expect(await isEnabled("qa.kag", { tenantId: TENANT_A })).toBe(false);
    expect(await flagValue("flags.provider")).toBe("env");
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("throws on an unknown flag and on the wrong reader", async () => {
    await expect(isEnabled("demo.nowhere")).rejects.toThrow(UnknownFlagError);
    await expect(flagValue("demo.nowhere")).rejects.toThrow(UnknownFlagError);
    await expect(isEnabled("flags.provider")).rejects.toThrow("read it with flagValue");
    await expect(flagValue("qa.kag")).rejects.toThrow("read it with isEnabled");
  });
});

describe("the env provider", () => {
  it("applies the default without a variable", async () => {
    await useEnv({});
    expect(await isEnabled("demo.switch")).toBe(false);
    expect(await flagValue("demo.provider")).toBe("none");
  });

  it.each([
    ["true", true],
    ["1", true],
    ["yes", true],
    ["ON", true],
    ["false", false],
    ["0", false],
  ])("reads %s from the variable the code already uses", async (raw, expected) => {
    await useEnv({ CW_DEMO_ENABLED: raw });
    expect(await isEnabled("demo.switch")).toBe(expected);
  });

  it("reads CW_FLAG_<NAME> when the code has no variable set", async () => {
    await useEnv({ CW_FLAG_DEMO_SWITCH: "true" });
    expect(await isEnabled("demo.switch")).toBe(true);
    await useEnv({ CW_DEMO_ENABLED: "false", CW_FLAG_DEMO_SWITCH: "true" });
    expect(await isEnabled("demo.switch")).toBe(false);
    await useEnv({ CW_DEMO_ENABLED: " ", CW_FLAG_DEMO_SWITCH: "true" });
    expect(await isEnabled("demo.switch")).toBe(true);
  });

  it("answers the default for a malformed value and logs it", async () => {
    await useEnv({ CW_DEMO_ENABLED: "maybe" });
    expect(await isEnabled("demo.switch")).toBe(false);
    expect(logged()).toEqual([
      {
        event: "flag_evaluation_failed",
        flag: "demo.switch",
        error_code: "PARSE_ERROR",
        error: 'CW_DEMO_ENABLED="maybe" is not true or false',
        value: false,
      },
    ]);
  });

  it("narrows a flag that is on to its tenant allow-list", async () => {
    await useEnv({
      CW_DEMO_TENANTED_ENABLED: "true",
      CW_DEMO_TENANTS: ` ${TENANT_A.toUpperCase()} ,`,
    });
    expect(await isEnabled("demo.tenanted", { tenantId: TENANT_A })).toBe(true);
    expect(await isEnabled("demo.tenanted", { tenantId: TENANT_B })).toBe(false);
    expect(await isEnabled("demo.tenanted")).toBe(false);
  });

  it("does not turn a flag on through its allow-list", async () => {
    await useEnv({ CW_DEMO_TENANTS: TENANT_A });
    expect(await isEnabled("demo.tenanted", { tenantId: TENANT_A })).toBe(false);
  });

  it("turns a flag without an allow-list on for every tenant", async () => {
    await useEnv({ CW_DEMO_TENANTED_ENABLED: "true" });
    expect(await isEnabled("demo.tenanted", { tenantId: TENANT_B })).toBe(true);
    expect(await isEnabled("demo.tenanted")).toBe(true);
  });

  it("reads a new flag and its tenants from the CW_FLAG_ variables", async () => {
    await useEnv({ CW_FLAG_DEMO_FRESH: "true", CW_FLAG_DEMO_FRESH__TENANTS: TENANT_B });
    expect(await isEnabled("demo.fresh", { tenantId: TENANT_B })).toBe(true);
    expect(await isEnabled("demo.fresh", { tenantId: TENANT_A })).toBe(false);
  });

  it("ignores a tenant list on an untargeted flag", async () => {
    await useEnv({ CW_DEMO_ENABLED: "true", CW_FLAG_DEMO_SWITCH__TENANTS: TENANT_A });
    expect(await isEnabled("demo.switch", { tenantId: TENANT_B })).toBe(true);
  });

  it("answers off for a malformed tenant id", async () => {
    await useEnv({ CW_DEMO_TENANTED_ENABLED: "true", CW_DEMO_TENANTS: "acme" });
    expect(await isEnabled("demo.tenanted", { tenantId: TENANT_A })).toBe(false);
    expect(logged()[0]?.error).toBe('"acme" is not a tenant id');
    await useEnv({ CW_DEMO_TENANTED_ENABLED: "true", CW_DEMO_TENANTS: TENANT_A });
    expect(await isEnabled("demo.tenanted", { tenantId: "not-a-uuid" })).toBe(false);
  });

  it("takes a string flag's value from its values only", async () => {
    await useEnv({ CW_DEMO_PROVIDER: "sandbox" });
    expect(await flagValue("demo.provider")).toBe("sandbox");
    await useEnv({ CW_DEMO_PROVIDER: "http" });
    expect(await flagValue("demo.provider")).toBe("none");
    expect(logged()[0]?.error).toBe('CW_DEMO_PROVIDER="http" is not one of ["none","sandbox"]');
  });

  it("refuses other types and unknown keys", async () => {
    const provider = new EnvProvider({}, TEST_REGISTRY);
    const context: EvaluationContext = {};
    expect(provider.metadata.name).toBe("env");
    await expect(provider.resolveBooleanEvaluation("demo.nowhere", false, context)).rejects.toThrow(
      "no flag named",
    );
    await expect(provider.resolveStringEvaluation("demo.switch", "", context)).rejects.toThrow(
      TypeMismatchError,
    );
    await expect(provider.resolveNumberEvaluation()).rejects.toThrow(TypeMismatchError);
    await expect(provider.resolveObjectEvaluation()).rejects.toThrow(TypeMismatchError);
  });

  it("reads process.env by default", async () => {
    const provider = new EnvProvider();
    const result = await provider.resolveBooleanEvaluation("qa.kag", false, {});
    expect(typeof result.value).toBe("boolean");
  });

  it("goes back to the defaults on reset", async () => {
    await useEnv({ CW_DEMO_ENABLED: "true" });
    expect(await isEnabled("demo.switch")).toBe(true);
    await resetFlags();
    await expect(isEnabled("demo.switch")).rejects.toThrow(UnknownFlagError);
    expect(await isEnabled("qa.kag")).toBe(false);
  });

  it("refuses a provider it does not know", async () => {
    await expect(configureFlags({ CW_FLAGS_PROVIDER: "launchdarkly" })).rejects.toThrow(
      'CW_FLAGS_PROVIDER is env or unleash, not "launchdarkly"',
    );
  });

  it("is the default provider", async () => {
    const provider = await configureFlags({}, { registry: TEST_REGISTRY });
    expect(provider.metadata.name).toBe("env");
    expect(OpenFeature.getProviderMetadata(DOMAIN).name).toBe("env");
  });
});

class FakeUnleash implements UnleashClient {
  readonly features = new Map<string, (context: UnleashContext) => boolean>();
  readonly variants = new Map<string, Variant>();
  readonly contexts: (UnleashContext | undefined)[] = [];
  readonly listeners = new Map<string, (problem: unknown) => void>();
  started = false;
  destroyed = false;

  async start(): Promise<void> {
    this.started = true;
  }

  destroy(): void {
    this.destroyed = true;
  }

  isEnabled(
    name: string,
    context?: UnleashContext,
    fallbackFunction?: (name: unknown, context: UnleashContext) => boolean,
  ): boolean {
    this.contexts.push(context);
    const rule = this.features.get(name);
    if (rule === undefined) return fallbackFunction ? fallbackFunction(name, context ?? {}) : false;
    return rule(context ?? {});
  }

  getVariant(name: string, context?: UnleashContext): Variant {
    this.contexts.push(context);
    return this.variants.get(name) ?? { name: "disabled", enabled: false };
  }

  on(event: "error" | "warn", listener: (problem: unknown) => void): this {
    this.listeners.set(event, listener);
    return this;
  }
}

const UNLEASH_ENV: Environment = {
  CW_FLAGS_PROVIDER: "unleash",
  CW_UNLEASH_URL: UNLEASH_URL,
  CW_UNLEASH_API_TOKEN: UNLEASH_CLIENT_TOKEN,
};

async function useUnleash(client: FakeUnleash): Promise<void> {
  await configureFlags(UNLEASH_ENV, { registry: TEST_REGISTRY, log, unleashClient: client });
}

describe("the Unleash provider", () => {
  it("starts the client on configure and destroys it on close", async () => {
    const client = new FakeUnleash();
    const provider = await configureFlags(UNLEASH_ENV, {
      registry: TEST_REGISTRY,
      unleashClient: client,
    });
    expect(client.started).toBe(true);
    expect(provider.metadata.name).toBe("unleash");
    await provider.onClose?.();
    expect(client.destroyed).toBe(true);
  });

  it("answers a flag for the tenant", async () => {
    const client = new FakeUnleash();
    client.features.set("demo.tenanted", (context) => context.userId === TENANT_A);
    await useUnleash(client);
    expect(await isEnabled("demo.tenanted", { tenantId: TENANT_A.toUpperCase() })).toBe(true);
    expect(await isEnabled("demo.tenanted", { tenantId: TENANT_B })).toBe(false);
    expect(await isEnabled("demo.tenanted")).toBe(false);
    expect(client.contexts).toEqual([
      { userId: TENANT_A, properties: { tenantId: TENANT_A } },
      { userId: TENANT_B, properties: { tenantId: TENANT_B } },
      {},
    ]);
  });

  it("answers the default for a flag Unleash does not hold", async () => {
    await useUnleash(new FakeUnleash());
    expect(await isEnabled("demo.switch")).toBe(false);
    expect(logged()[0]).toMatchObject({
      error_code: "FLAG_NOT_FOUND",
      error: 'Unleash has no flag named "demo.switch"',
    });
  });

  it("reads a string flag from a variant", async () => {
    const client = new FakeUnleash();
    await useUnleash(client);
    client.variants.set("demo.provider", {
      name: "rollout",
      enabled: true,
      payload: { type: PayloadType.STRING, value: "sandbox" },
    });
    expect(await flagValue("demo.provider", { tenantId: TENANT_A })).toBe("sandbox");
    client.variants.set("demo.provider", { name: "sandbox", enabled: true });
    expect(await flagValue("demo.provider")).toBe("sandbox");
    client.variants.set("demo.provider", { name: "disabled", enabled: false });
    expect(await flagValue("demo.provider")).toBe("none");
    client.variants.set("demo.provider", { name: "http", enabled: true });
    expect(await flagValue("demo.provider")).toBe("none");
    expect(logged()[0]?.error).toBe('Unleash variant "http" is not one of ["none","sandbox"]');
  });

  it("logs the client's errors and warnings instead of crashing", async () => {
    const client = new FakeUnleash();
    await useUnleash(client);
    client.listeners.get("error")?.(new Error("connect ECONNREFUSED"));
    client.listeners.get("warn")?.("not synchronized");
    expect(logged()).toEqual([
      { event: "unleash_error", error: "Error: connect ECONNREFUSED" },
      { event: "unleash_warning", warning: "not synchronized" },
    ]);
  });

  it("checks the registry before asking Unleash", async () => {
    const provider = new UnleashProvider(new FakeUnleash(), TEST_REGISTRY, log);
    await expect(provider.resolveBooleanEvaluation("demo.nowhere", false, {})).rejects.toThrow(
      "no flag named",
    );
    await expect(provider.resolveBooleanEvaluation("demo.provider", false, {})).rejects.toThrow(
      TypeMismatchError,
    );
    await expect(provider.resolveNumberEvaluation()).rejects.toThrow(TypeMismatchError);
    await expect(provider.resolveObjectEvaluation()).rejects.toThrow(TypeMismatchError);
  });

  it("needs the URL and the token", async () => {
    await expect(configureFlags({ CW_FLAGS_PROVIDER: "unleash" })).rejects.toThrow(
      "CW_FLAGS_PROVIDER=unleash needs CW_UNLEASH_URL and CW_UNLEASH_API_TOKEN",
    );
  });

  it("builds a real client that has not started", async () => {
    const client = await createUnleashClient(UNLEASH_ENV, "compliancewatch-test");
    expect(typeof client.isEnabled).toBe("function");
    expect(client.isEnabled("demo.switch", {}, () => false)).toBe(false);
    client.destroy();
  });
});
