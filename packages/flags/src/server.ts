/**
 * Feature flags for TypeScript servers through the OpenFeature server SDK, over the registry
 * (packages/flags/registry.json). It answers as py_common.flags does for the Python services.
 *
 * configureFlags(env) installs the provider CW_FLAGS_PROVIDER names:
 * - env (the default): EnvProvider. A flag's value comes from the variable the code already reads
 *   (the entry's env), else from CW_FLAG_<NAME>, else the registry default. A tenant-targeted
 *   flag that is on applies to the tenants in its allow-list (the entry's tenants_env or
 *   CW_FLAG_<NAME>__TENANTS, comma-separated tenant ids); with no list it applies to every tenant.
 * - unleash: UnleashProvider over unleash-client, at CW_UNLEASH_URL with the client token
 *   CW_UNLEASH_API_TOKEN. The flag's registry name is its Unleash name and the tenant id is the
 *   targeting key (Unleash's userId, and the tenantId property for constraints).
 *
 * isEnabled(name, { tenantId }) answers a bool flag and flagValue(name, { tenantId }) a string
 * flag. A name the registry does not hold throws UnknownFlagError. A provider error, such as a
 * malformed value or a flag Unleash does not know, answers the registry default, which is off,
 * and is logged. Until configureFlags runs, every flag answers its default and each evaluation
 * logs that no provider is ready, so a server that forgot to configure its flags shows it.
 */
import {
  FlagNotFoundError,
  OpenFeature,
  ParseError,
  StandardResolutionReasons,
  TypeMismatchError,
  type EvaluationContext,
  type EvaluationDetails,
  type FlagValue,
  type JsonValue,
  type Provider,
  type ResolutionDetails,
} from "@openfeature/server-sdk";
import type { Context as UnleashContext, Variant } from "unleash-client";
import {
  REGISTRY,
  overrideEnv,
  tenantsOverrideEnv,
  type FlagDefinition,
  type FlagRegistry,
} from "./index.ts";

/** The OpenFeature domain the provider is bound to, so another library's provider is left alone. */
export const DOMAIN = "compliancewatch";

export type Environment = Readonly<Record<string, string | undefined>>;
/** Where failed evaluations and the Unleash client's problems go, one JSON line each;
 * console.warn by default. */
export type FlagLog = (line: string) => void;

const TRUE = new Set(["true", "1", "yes", "on"]);
const FALSE = new Set(["false", "0", "no", "off"]);
const TENANT_ID = /^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$/i;
const NOT_BOOL_OR_STRING = "registry flags are bool or string";

/** A tenant id in canonical form (lower case, hyphenated), or ParseError. */
export function canonicalTenant(value: string): string {
  const trimmed = value.trim();
  if (!TENANT_ID.test(trimmed))
    throw new ParseError(`${JSON.stringify(trimmed)} is not a tenant id`);
  const hex = trimmed.replaceAll("-", "").toLowerCase();
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

function tenantOf(context: EvaluationContext): string | undefined {
  return context.targetingKey ? canonicalTenant(context.targetingKey) : undefined;
}

function definitionOf(
  registry: FlagRegistry,
  flagKey: string,
  type: FlagDefinition["type"],
): FlagDefinition {
  if (!registry.has(flagKey))
    throw new FlagNotFoundError(`no flag named ${JSON.stringify(flagKey)} in the registry`);
  const definition = registry.get(flagKey);
  if (definition.type !== type) {
    throw new TypeMismatchError(`${flagKey} is a ${definition.type} flag, not a ${type} flag`);
  }
  return definition;
}

/** Flags from environment variables, with a tenant allow-list per targeted flag. */
export class EnvProvider implements Provider {
  readonly metadata = { name: "env" } as const;
  readonly runsOn = "server" as const;
  readonly #env: Environment;
  readonly #registry: FlagRegistry;

  constructor(env: Environment = process.env, registry: FlagRegistry = REGISTRY) {
    this.#env = env;
    this.#registry = registry;
  }

  /** The variable that sets the flag and its value: the variable the code already reads first. */
  #raw(definition: FlagDefinition): [string, string] | undefined {
    for (const variable of [definition.env, overrideEnv(definition.name)]) {
      const value = variable === undefined ? undefined : this.#env[variable]?.trim();
      if (variable !== undefined && value) return [variable, value];
    }
    return undefined;
  }

  #allowList(definition: FlagDefinition): Set<string> {
    for (const variable of [definition.tenants_env, tenantsOverrideEnv(definition.name)]) {
      const raw = variable === undefined ? undefined : this.#env[variable]?.trim();
      if (raw) {
        return new Set(
          raw
            .split(",")
            .filter((part) => part.trim())
            .map(canonicalTenant),
        );
      }
    }
    return new Set();
  }

  async resolveBooleanEvaluation(
    flagKey: string,
    _defaultValue: boolean,
    context: EvaluationContext,
  ): Promise<ResolutionDetails<boolean>> {
    const definition = definitionOf(this.#registry, flagKey, "bool");
    const raw = this.#raw(definition);
    if (raw === undefined) {
      return { value: definition.default === true, reason: StandardResolutionReasons.DEFAULT };
    }
    const [variable, text] = raw;
    const lowered = text.toLowerCase();
    if (!TRUE.has(lowered) && !FALSE.has(lowered)) {
      throw new ParseError(`${variable}=${JSON.stringify(text)} is not true or false`);
    }
    if (FALSE.has(lowered)) return { value: false, reason: StandardResolutionReasons.STATIC };
    const allowed =
      definition.targeting === "tenant" ? this.#allowList(definition) : new Set<string>();
    if (allowed.size === 0) return { value: true, reason: StandardResolutionReasons.STATIC };
    const tenant = tenantOf(context);
    const on = tenant !== undefined && allowed.has(tenant);
    return {
      value: on,
      reason: on ? StandardResolutionReasons.TARGETING_MATCH : StandardResolutionReasons.DEFAULT,
    };
  }

  async resolveStringEvaluation(
    flagKey: string,
    _defaultValue: string,
    _context: EvaluationContext,
  ): Promise<ResolutionDetails<string>> {
    const definition = definitionOf(this.#registry, flagKey, "string");
    const raw = this.#raw(definition);
    if (raw === undefined) {
      return { value: String(definition.default), reason: StandardResolutionReasons.DEFAULT };
    }
    const [variable, text] = raw;
    if (!definition.values?.includes(text)) {
      throw new ParseError(
        `${variable}=${JSON.stringify(text)} is not one of ${JSON.stringify(definition.values ?? [])}`,
      );
    }
    return { value: text, reason: StandardResolutionReasons.STATIC };
  }

  async resolveNumberEvaluation(): Promise<ResolutionDetails<number>> {
    throw new TypeMismatchError(NOT_BOOL_OR_STRING);
  }

  async resolveObjectEvaluation<T extends JsonValue>(): Promise<ResolutionDetails<T>> {
    throw new TypeMismatchError(NOT_BOOL_OR_STRING);
  }
}

/** The part of unleash-client's Unleash class the provider uses. */
export interface UnleashClient {
  start(): Promise<void>;
  destroy(): void;
  isEnabled(
    name: string,
    context?: UnleashContext,
    fallbackFunction?: (name: unknown, context: UnleashContext) => boolean,
  ): boolean;
  getVariant(name: string, context?: UnleashContext): Variant;
  on(event: "error" | "warn", listener: (problem: unknown) => void): unknown;
}

/** An Unleash client for CW_UNLEASH_URL and CW_UNLEASH_API_TOKEN, loaded only when asked for. */
export async function createUnleashClient(
  env: Environment,
  appName: string,
): Promise<UnleashClient> {
  const url = env.CW_UNLEASH_URL?.trim();
  const token = env.CW_UNLEASH_API_TOKEN?.trim();
  if (!url || !token) {
    throw new Error("CW_FLAGS_PROVIDER=unleash needs CW_UNLEASH_URL and CW_UNLEASH_API_TOKEN");
  }
  const { Unleash } = await import("unleash-client");
  return new Unleash({
    url,
    appName,
    customHeaders: { Authorization: token },
    disableAutoStart: true,
    skipInstanceCountWarning: true,
  });
}

/** Flags from an Unleash server. The client polls it in the background; an evaluation reads the
 * client's last copy and makes no request. */
export class UnleashProvider implements Provider {
  readonly metadata = { name: "unleash" } as const;
  readonly runsOn = "server" as const;
  readonly #client: UnleashClient;
  readonly #registry: FlagRegistry;

  constructor(
    client: UnleashClient,
    registry: FlagRegistry = REGISTRY,
    log: FlagLog = console.warn,
  ) {
    this.#client = client;
    this.#registry = registry;
    // An EventEmitter without an error listener throws; Unleash being unreachable is not fatal.
    client.on("error", (problem) =>
      log(JSON.stringify({ event: "unleash_error", error: String(problem) })),
    );
    client.on("warn", (problem) =>
      log(JSON.stringify({ event: "unleash_warning", warning: String(problem) })),
    );
  }

  async initialize(): Promise<void> {
    await this.#client.start();
  }

  async onClose(): Promise<void> {
    this.#client.destroy();
  }

  static context(context: EvaluationContext): UnleashContext {
    const tenant = tenantOf(context);
    return tenant === undefined ? {} : { userId: tenant, properties: { tenantId: tenant } };
  }

  async resolveBooleanEvaluation(
    flagKey: string,
    _defaultValue: boolean,
    context: EvaluationContext,
  ): Promise<ResolutionDetails<boolean>> {
    const definition = definitionOf(this.#registry, flagKey, "bool");
    const unleashContext = UnleashProvider.context(context);
    let known = true;
    const value = this.#client.isEnabled(flagKey, unleashContext, () => {
      known = false;
      return definition.default === true;
    });
    if (!known) throw new FlagNotFoundError(`Unleash has no flag named ${JSON.stringify(flagKey)}`);
    const reason = unleashContext.userId
      ? StandardResolutionReasons.TARGETING_MATCH
      : StandardResolutionReasons.STATIC;
    return { value, reason };
  }

  /** A string flag is an Unleash variant: the payload's value, else the variant's name. */
  async resolveStringEvaluation(
    flagKey: string,
    _defaultValue: string,
    context: EvaluationContext,
  ): Promise<ResolutionDetails<string>> {
    const definition = definitionOf(this.#registry, flagKey, "string");
    const variant = this.#client.getVariant(flagKey, UnleashProvider.context(context));
    if (!variant.enabled) {
      return { value: String(definition.default), reason: StandardResolutionReasons.DISABLED };
    }
    const value = variant.payload?.type === "string" ? variant.payload.value : variant.name;
    if (!definition.values?.includes(value)) {
      throw new ParseError(
        `Unleash variant ${JSON.stringify(value)} is not one of ${JSON.stringify(definition.values ?? [])}`,
      );
    }
    return { value, variant: variant.name, reason: StandardResolutionReasons.SPLIT };
  }

  async resolveNumberEvaluation(): Promise<ResolutionDetails<number>> {
    throw new TypeMismatchError(NOT_BOOL_OR_STRING);
  }

  async resolveObjectEvaluation<T extends JsonValue>(): Promise<ResolutionDetails<T>> {
    throw new TypeMismatchError(NOT_BOOL_OR_STRING);
  }
}

export interface FlagOptions {
  /** The registry to evaluate (tests); every registered flag by default. */
  readonly registry?: FlagRegistry;
  readonly log?: FlagLog;
  /** Replaces the real Unleash client (tests). */
  readonly unleashClient?: UnleashClient;
  /** Unleash's appName is compliancewatch-<serviceName>. */
  readonly serviceName?: string;
}

let current: { registry: FlagRegistry; log: FlagLog } = { registry: REGISTRY, log: console.warn };

/** Install the provider CW_FLAGS_PROVIDER names and wait until it is ready. */
export async function configureFlags(
  env: Environment = process.env,
  options: FlagOptions = {},
): Promise<Provider> {
  const registry = options.registry ?? REGISTRY;
  const log = options.log ?? console.warn;
  const kind = env.CW_FLAGS_PROVIDER?.trim() || "env";
  let provider: Provider;
  if (kind === "unleash") {
    const client =
      options.unleashClient ??
      (await createUnleashClient(env, `compliancewatch-${options.serviceName ?? "node"}`));
    provider = new UnleashProvider(client, registry, log);
  } else if (kind === "env") {
    provider = new EnvProvider(env, registry);
  } else {
    throw new Error(`CW_FLAGS_PROVIDER is env or unleash, not ${JSON.stringify(kind)}`);
  }
  await OpenFeature.setProviderAndWait(DOMAIN, provider);
  current = { registry, log };
  return provider;
}

/** Back to every flag's default, with nothing read from the environment (tests). */
export async function resetFlags(): Promise<void> {
  await OpenFeature.setProviderAndWait(DOMAIN, new EnvProvider({}));
  current = { registry: REGISTRY, log: console.warn };
}

export interface Target {
  /** The tenant the flag is evaluated for; a targeted flag with an allow-list is off without one. */
  readonly tenantId?: string;
}

function contextOf({ tenantId }: Target): EvaluationContext {
  return tenantId ? { targetingKey: tenantId } : {};
}

function answer<T extends FlagValue>(details: EvaluationDetails<T>): T {
  if (details.errorCode !== undefined) {
    current.log(
      JSON.stringify({
        event: "flag_evaluation_failed",
        flag: details.flagKey,
        error_code: details.errorCode,
        error: details.errorMessage,
        value: details.value,
      }),
    );
  }
  return details.value;
}

/** Whether the bool flag is on, for the tenant when the flag targets tenants. */
export async function isEnabled(name: string, target: Target = {}): Promise<boolean> {
  const definition = current.registry.get(name);
  if (definition.type !== "bool")
    throw new TypeError(`${name} is a string flag; read it with flagValue`);
  const client = OpenFeature.getClient(DOMAIN);
  return answer(
    await client.getBooleanDetails(name, definition.default === true, contextOf(target)),
  );
}

/** The value of the string flag, one of its registered values. */
export async function flagValue(name: string, target: Target = {}): Promise<string> {
  const definition = current.registry.get(name);
  if (definition.type !== "string")
    throw new TypeError(`${name} is a bool flag; read it with isEnabled`);
  const client = OpenFeature.getClient(DOMAIN);
  return answer(await client.getStringDetails(name, String(definition.default), contextOf(target)));
}
