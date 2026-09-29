import "server-only";

/**
 * The runtime environment name, read straight from CW_WEB_ENV. The validated, memoised
 * environment module arrives with the data layer; until then the two callers (the admin
 * shell's label and the design catalogue gate) read this one variable. Unset means local;
 * a value outside the known set is treated as prod so a typo never opens a local-only page.
 */
export const WEB_ENVS = ["local", "test", "staging", "prod"] as const;

export type WebEnvName = (typeof WEB_ENVS)[number];

export function isWebEnvName(value: string): value is WebEnvName {
  return (WEB_ENVS as readonly string[]).includes(value);
}

export type EnvRecord = Readonly<Record<string, string | undefined>>;

export function webEnvName(env: EnvRecord = process.env): WebEnvName {
  const value = env.CW_WEB_ENV;
  if (value === undefined || value === "") return "local";
  return isWebEnvName(value) ? value : "prod";
}

/** Local-only pages (the design catalogue, the fake sign-in) exist only in these two. */
export function isLocalOrTest(env: EnvRecord = process.env): boolean {
  const name = webEnvName(env);
  return name === "local" || name === "test";
}
