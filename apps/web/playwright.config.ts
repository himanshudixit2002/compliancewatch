import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against `next start` on PORT (3000 unless set; the ui clone uses 3200). The server is
 * started with CW_WEB_ENV=test so the local-only pages exist, with the fake sign-in provider so
 * the specs can sign in through the form, and with a fixed session secret (32 bytes of "e2e",
 * not a secret: it only keys the cookies of this run). No page on `main` calls a service. The
 * one test that needs the services is the seeded-tenant sign-in: it runs once `make web-stack`,
 * `make web-stack-wait` and `make web-seed` have written var/seed/last.json (the CI job runs
 * them first and fails the test without that file; elsewhere it is skipped).
 */
const PORT = Number(process.env.PORT ?? 3000);
const BASE_URL = `http://localhost:${PORT}`;
const CI = process.env.CI !== undefined && process.env.CI !== "" && process.env.CI !== "false";
const E2E_SESSION_SECRET = Buffer.alloc(32, "e2e").toString("base64");

export default defineConfig({
  testDir: "e2e",
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  reporter: CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: BASE_URL, trace: "on-first-retry" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
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
    },
  },
});
