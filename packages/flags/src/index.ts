/**
 * The feature flag registry (registry.json) for TypeScript: every flag's definition by name and
 * the environment variables the env provider reads for it. Nothing here needs Node, so any
 * runtime can import it; the OpenFeature client for servers is in ./server.ts.
 */
import data from "../registry.json" with { type: "json" };

export type FlagOwner =
  "core-product" | "platform" | "regulatory-intelligence" | "ai-platform" | "identity-partner";

/** One registry entry (registry.schema.json). */
export interface FlagDefinition {
  readonly name: string;
  readonly type: "bool" | "string";
  readonly default: boolean | string;
  readonly values?: readonly string[];
  readonly owner: FlagOwner;
  readonly description: string;
  readonly removal: string;
  readonly expires: string;
  readonly targeting: "none" | "tenant";
  readonly env?: string;
  readonly tenants_env?: string;
  readonly services: readonly string[];
}

/** The code asked for a flag that packages/flags/registry.json does not hold. */
export class UnknownFlagError extends Error {
  readonly flag: string;

  constructor(flag: string) {
    super(`no flag named ${JSON.stringify(flag)} in packages/flags/registry.json`);
    this.name = "UnknownFlagError";
    this.flag = flag;
  }
}

/** The registered flags, looked up by name. */
export class FlagRegistry {
  readonly flags: readonly FlagDefinition[];
  readonly #byName: ReadonlyMap<string, FlagDefinition>;

  constructor(flags: readonly FlagDefinition[]) {
    this.flags = flags;
    this.#byName = new Map(flags.map((flag) => [flag.name, flag]));
  }

  has(name: string): boolean {
    return this.#byName.has(name);
  }

  get(name: string): FlagDefinition {
    const flag = this.#byName.get(name);
    if (flag === undefined) throw new UnknownFlagError(name);
    return flag;
  }
}

/** Every flag in packages/flags/registry.json. */
export const REGISTRY = new FlagRegistry(data.flags as readonly FlagDefinition[]);

export const OVERRIDE_PREFIX = "CW_FLAG_";
export const TENANTS_SUFFIX = "__TENANTS";

/** CW_FLAG_<NAME>: sets a flag by its registry name (dots become underscores). */
export function overrideEnv(name: string): string {
  return OVERRIDE_PREFIX + name.toUpperCase().replaceAll(".", "_");
}

/** CW_FLAG_<NAME>__TENANTS: the tenant allow-list of a flag by its registry name. */
export function tenantsOverrideEnv(name: string): string {
  return overrideEnv(name) + TENANTS_SUFFIX;
}
