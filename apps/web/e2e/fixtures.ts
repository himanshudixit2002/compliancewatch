import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test as base } from "@playwright/test";
import type { Browser, BrowserContext, Page } from "@playwright/test";
import type { Role, TenantKind } from "../src/shared/config/roles.ts";
import { isVisibleTo } from "../src/shared/config/screens.ts";
import type { Screen } from "../src/shared/config/screens.ts";

/** Impacts that fail a page; moderate and minor findings are reported by the unit-level axe. */
export const FAILING_IMPACTS: readonly string[] = ["serious", "critical"];

/** True on CI, where the job starts the services and seeds them before the suite. */
export const IS_CI =
  process.env.CI !== undefined && process.env.CI !== "" && process.env.CI !== "false";

/** Where the seed records its tenant, relative to apps/web: the app's own default. */
const DEFAULT_SEED_STATE_PATH = "../../var/seed/last.json";

/**
 * The tenant `make web-seed` filled last, read from the file the app reads for the sign-in
 * form's "last seeded tenant" option (CW_WEB_SEED_STATE_PATH relative to apps/web, else
 * var/seed/last.json at the repository root); null when the seed has not run here.
 */
export function seededTenantId(): string | null {
  const configured = process.env.CW_WEB_SEED_STATE_PATH?.trim();
  const path = resolve(__dirname, "..", configured || DEFAULT_SEED_STATE_PATH);
  try {
    const state: unknown = JSON.parse(readFileSync(path, "utf8"));
    if (typeof state === "object" && state !== null && "tenant_id" in state) {
      return typeof state.tenant_id === "string" ? state.tenant_id : null;
    }
  } catch {
    // Absent or unreadable: the seed has not run on this machine.
  }
  return null;
}

const SERVICE_ORDER = [
  "identity",
  "profile",
  "rulebook",
  "applicability-engine",
  "obligation",
  "notification",
  "qa",
  "llm-gateway",
  "eval",
  "pipeline",
] as const;

/**
 * Where a service of the running stack listens, for a spec that reads back what a page wrote:
 * CW_WEB_<SERVICE>_URL when set, else SERVICE_PORT_BASE + its position in the Makefile's
 * SERVICES order (8001-8010 by default), the same rule make web-stack and make web-e2e use.
 */
export function serviceUrl(service: (typeof SERVICE_ORDER)[number]): string {
  const configured = process.env[`CW_WEB_${service.toUpperCase().replace(/-/g, "_")}_URL`]?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  const base = Number(process.env.SERVICE_PORT_BASE ?? 8000);
  return `http://localhost:${base + SERVICE_ORDER.indexOf(service) + 1}`;
}

export interface ViolationSummary {
  id: string;
  impact: string;
  help: string;
  targets: string[];
}

/** Runs axe on the page (or one selector) and returns the serious and critical violations. */
export async function seriousViolations(page: Page, include?: string): Promise<ViolationSummary[]> {
  let builder = new AxeBuilder({ page });
  if (include !== undefined) builder = builder.include(include);
  const results = await builder.analyze();
  return results.violations
    .filter(
      (violation) =>
        typeof violation.impact === "string" && FAILING_IMPACTS.includes(violation.impact),
    )
    .map((violation) => ({
      id: violation.id,
      impact: violation.impact ?? "unknown",
      help: violation.help,
      targets: violation.nodes.map((node) => node.target.join(" ")),
    }));
}

/** What the fake sign-in form is filled with. */
export interface Persona {
  key: string;
  tenantKind: TenantKind;
  roles: readonly Role[];
  displayName: string;
  tenantId?: string;
}

export const OWNER: Persona = {
  key: "owner",
  tenantKind: "business",
  roles: ["owner"],
  displayName: "Example owner",
};

export const COMPLIANCE_LEAD: Persona = {
  key: "compliance-lead",
  tenantKind: "business",
  roles: ["compliance_lead"],
  displayName: "Example compliance lead",
};

export const CA_ADMIN: Persona = {
  key: "ca-admin",
  tenantKind: "ca_firm",
  roles: ["ca_admin"],
  displayName: "Example CA admin",
  tenantId: "00000000-0000-4000-8000-00000000000c",
};

export const ANALYST: Persona = {
  key: "analyst",
  tenantKind: "internal",
  roles: ["analyst"],
  displayName: "Example analyst",
};

export const ADMIN: Persona = {
  key: "admin",
  tenantKind: "internal",
  roles: ["admin"],
  displayName: "Example admin",
};

/** The personas the sweep tries, in order; the first one a screen admits is used. */
export const PERSONAS: readonly Persona[] = [OWNER, COMPLIANCE_LEAD, CA_ADMIN, ADMIN];

/** The first persona that may open the screen, or null for a public one. */
export function personaFor(screen: Screen): Persona | null {
  if (screen.roles === "public") return null;
  const persona = PERSONAS.find((candidate) =>
    isVisibleTo(screen, candidate.roles, candidate.tenantKind),
  );
  if (persona === undefined) throw new Error(`no persona may open ${screen.id}`);
  return persona;
}

const ROLE_LABELS: Readonly<Record<Role, string>> = {
  owner: "Owner",
  staff: "Staff",
  ca_admin: "CA admin",
  ca_staff: "CA staff",
  compliance_lead: "Compliance lead",
  analyst: "Analyst",
  reviewer: "Reviewer",
  admin: "Admin",
};

/**
 * Resolves once React has hydrated the element: a controlled input filled before hydration is
 * reset to its state when React takes over, so a spec waits for this before typing into one.
 */
export async function waitForHydration(page: Page, selector: string): Promise<void> {
  await page.waitForFunction((target) => {
    const element = document.querySelector(target);
    return element !== null && Object.keys(element).some((key) => key.startsWith("__react"));
  }, selector);
}

/** Fills and submits the fake sign-in form on the page; resolves once the redirect landed. */
export async function signInThroughForm(
  page: Page,
  persona: Persona,
  next?: string,
): Promise<void> {
  await page.goto(next === undefined ? "/sign-in" : `/sign-in?next=${encodeURIComponent(next)}`);
  // The tenant id is a controlled input: typed before hydration, it would be reset to empty and
  // the session would get a new tenant.
  await waitForHydration(page, 'input[name="tenantId"]');
  await page.getByLabel("Tenant kind").selectOption(persona.tenantKind);
  for (const role of persona.roles) {
    await page.getByRole("checkbox", { name: ROLE_LABELS[role] }).check();
  }
  await page.getByLabel("Display name").fill(persona.displayName);
  if (persona.tenantId !== undefined) {
    const tenant = page.getByLabel("Tenant id");
    await tenant.fill(persona.tenantId);
    await expect(tenant).toHaveValue(persona.tenantId);
  }
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/sign-in"));
}

type StorageState = Awaited<ReturnType<BrowserContext["storageState"]>>;

const STATES = new Map<string, Promise<StorageState>>();

/** Signs the persona in once per worker (through the form) and returns the cookies to reuse. */
export function storageStateFor(
  browser: Browser,
  baseURL: string,
  persona: Persona,
): Promise<StorageState> {
  let state = STATES.get(persona.key);
  if (state === undefined) {
    state = (async () => {
      const context = await browser.newContext({ baseURL });
      const page = await context.newPage();
      await signInThroughForm(page, persona);
      const saved = await context.storageState();
      await context.close();
      return saved;
    })();
    STATES.set(persona.key, state);
  }
  return state;
}

export interface Fixtures {
  /** Fails the test when the page, or the given selector, has a serious or critical finding. */
  checkA11y: (include?: string) => Promise<void>;
  /** Gives the page the persona's session (signed in once per worker through the fake form). */
  signIn: (persona: Persona) => Promise<void>;
}

export const test = base.extend<Fixtures>({
  // Playwright calls the second argument "use"; it is named differently here so the React hooks
  // lint rule does not read it as a hook call.
  checkA11y: async ({ page }, provide) => {
    await provide(async (include) => {
      const violations = await seriousViolations(page, include);
      expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
    });
  },
  signIn: async ({ browser, baseURL, page }, provide) => {
    await provide(async (persona) => {
      const state = await storageStateFor(browser, baseURL ?? "http://localhost:3000", persona);
      await page.context().addCookies(state.cookies);
    });
  },
});

export { expect };
