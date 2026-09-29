import { defineConfig, devices } from "@playwright/test";

/**
 * Runs against `next start` on PORT (3000 unless set; the ui clone uses 3200). The server is
 * started with CW_WEB_ENV=test so the local-only pages exist; nothing else is configured and
 * no service is needed for the pages this suite visits.
 */
const PORT = Number(process.env.PORT ?? 3000);
const BASE_URL = `http://localhost:${PORT}`;
const CI = process.env.CI !== undefined && process.env.CI !== "" && process.env.CI !== "false";

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
    env: { PORT: String(PORT), CW_WEB_ENV: process.env.CW_WEB_ENV ?? "test" },
  },
});
