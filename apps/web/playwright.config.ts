import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against `next start` on PORT (3000 unless set; the ui clone uses 3200). The server is
 * started with CW_WEB_ENV=test so the local-only pages exist, with the fake sign-in provider so
 * the specs can sign in through the form, and with a fixed session secret (32 bytes of "e2e",
 * not a secret: it only keys the cookies of this run). The app gets the rulebook's two
 * placeholder tokens `make web-stack` gives the rulebook (unless the environment names others),
 * and the web.publish_actions, web.admin_rulebook_writes and web.qa_enabled flags on (their
 * overrides count in local and test only), so the rule version specs can cite, submit, approve and
 * return drafts, the review specs can decide entity groups and relation candidates, and the ask
 * specs can ask. The /admin allow-list is set (10.0.0.0/8, the proxy headers trusted) and every
 * request of the browser projects claims an address inside it, so the gate runs for real and
 * admin-allowlist.spec.ts can open a context from outside; /me is re-read every two seconds, so
 * revocation.spec.ts sees a disabled colleague signed out within a wait it can afford.
 *
 * Three projects:
 *   chromium     every spec but e2e/product, against the services `make web-stack` starts (`make
 *                web-e2e` points the app at their ports); the specs that need the services and
 *                the seeded tenant run once `make web-stack`, `make web-stack-wait` and `make
 *                web-seed` have written var/seed/last.json (the CI job runs them first and fails
 *                such a spec without that file; elsewhere it is skipped)
 *   stack-guard  what chromium depends on, so it runs first: the specs stage synthetic data
 *                through the services, so the run stops unless they are a memory stack `make
 *                web-stack` recorded (its directory in CW_E2E_WEB_STACK_DIR, var/web-stack by
 *                default) or E2E_ALLOW_POSTGRES=1 allows a Postgres one (scripts/stack-guard)
 *   product      e2e/product, the real-data journey against `make product` (its internal listener,
 *                every route of every service on one port) after `make product-seed`: set
 *                CW_E2E_PRODUCT_URL to that listener (http://127.0.0.1:8080) and every service URL
 *                of the app defaults to it (`make product-e2e`, and the CI dev-stack job, do so)
 *
 * The chromium and product projects drive Playwright's own Chromium (`make web-e2e-install`
 * downloads it once per machine; CI installs it) unless CW_E2E_BROWSER_CHANNEL names an installed
 * browser's channel to drive instead, such as chrome for Google Chrome (ComplianceWatch Control
 * sets it when Playwright's Chromium is missing and Chrome is installed). Unset or empty, nothing
 * changes. The stack-guard project starts no browser.
 */
const PORT = Number(process.env.PORT ?? 3000);
const BASE_URL = `http://localhost:${PORT}`;
const CI = process.env.CI !== undefined && process.env.CI !== "" && process.env.CI !== "false";
const E2E_SESSION_SECRET = Buffer.alloc(32, "e2e").toString("base64");

/** The /admin allow-list the e2e server runs with, and the address every request claims. */
export const E2E_ADMIN_ALLOWLIST = "10.0.0.0/8";
export const E2E_CLIENT_ADDRESS = "10.0.0.7";
/** How often the proxy re-reads /me in the e2e run, so a revocation shows within seconds. */
const E2E_RECHECK_SECONDS = "2";

/** The product's internal listener, when the product project is the one being run. */
const PRODUCT_URL = process.env.CW_E2E_PRODUCT_URL?.trim().replace(/\/+$/, "") || undefined;

/** An installed browser's channel to drive instead of Playwright's own Chromium. */
const CHANNEL = process.env.CW_E2E_BROWSER_CHANNEL?.trim() || undefined;

/** The browser of the chromium and product projects. */
const BROWSER = {
  ...devices["Desktop Chrome"],
  ...(CHANNEL === undefined ? {} : { channel: CHANNEL }),
};

/** The Makefile's SERVICES, as the app names their URL variables. */
const SERVICES = [
  "IDENTITY",
  "PROFILE",
  "RULEBOOK",
  "APPLICABILITY_ENGINE",
  "OBLIGATION",
  "NOTIFICATION",
  "QA",
  "LLM_GATEWAY",
  "EVAL",
  "PIPELINE",
] as const;

/** With the product named, every CW_WEB_<SERVICE>_URL the environment leaves unset points at it. */
function productServiceUrls(): Record<string, string> {
  if (PRODUCT_URL === undefined) return {};
  return Object.fromEntries(
    SERVICES.map((service) => {
      const name = `CW_WEB_${service}_URL`;
      return [name, process.env[name] ?? PRODUCT_URL];
    }),
  );
}

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [["list"], ["html", { open: "never" }]] : "list",
  // Every request names a client address inside the allow-list the server is started with
  // (below), so the /admin gate runs for real; admin-allowlist.spec.ts opens a context from
  // outside it.
  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    extraHTTPHeaders: { "x-forwarded-for": E2E_CLIENT_ADDRESS },
  },
  projects: [
    { name: "stack-guard", testMatch: /stack-guard\.setup\.ts$/ },
    {
      name: "chromium",
      testIgnore: "**/e2e/product/**",
      dependencies: ["stack-guard"],
      use: BROWSER,
    },
    { name: "product", testDir: "e2e/product", use: BROWSER },
  ],
  webServer: {
    command: "pnpm start",
    url: `${BASE_URL}/api/health`,
    reuseExistingServer: !CI,
    timeout: 60_000,
    env: {
      PORT: String(PORT),
      CW_WEB_ENV: process.env.CW_WEB_ENV ?? "test",
      CW_WEB_AUTH_PROVIDER: process.env.CW_WEB_AUTH_PROVIDER ?? "fake",
      CW_WEB_SESSION_SECRET: process.env.CW_WEB_SESSION_SECRET ?? E2E_SESSION_SECRET,
      CW_WEB_RULEBOOK_WRITE_TOKEN: process.env.CW_WEB_RULEBOOK_WRITE_TOKEN ?? "local-write-token",
      CW_WEB_RULEBOOK_REVIEW_TOKEN:
        process.env.CW_WEB_RULEBOOK_REVIEW_TOKEN ?? "local-review-token",
      CW_WEB_FLAG_PUBLISH_ACTIONS: process.env.CW_WEB_FLAG_PUBLISH_ACTIONS ?? "true",
      CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES: process.env.CW_WEB_FLAG_ADMIN_RULEBOOK_WRITES ?? "true",
      CW_WEB_FLAG_QA_ENABLED: process.env.CW_WEB_FLAG_QA_ENABLED ?? "true",
      // The /admin allow-list and the proxy headers it reads (the chromium project's requests
      // all carry a client address inside the list), and the re-read interval a revocation
      // spec waits for.
      CW_WEB_ADMIN_IP_ALLOWLIST: process.env.CW_WEB_ADMIN_IP_ALLOWLIST ?? E2E_ADMIN_ALLOWLIST,
      CW_WEB_TRUST_FORWARDED_IP: process.env.CW_WEB_TRUST_FORWARDED_IP ?? "true",
      CW_WEB_SESSION_RECHECK_SECONDS:
        process.env.CW_WEB_SESSION_RECHECK_SECONDS ?? E2E_RECHECK_SECONDS,
      ...productServiceUrls(),
    },
  },
});
