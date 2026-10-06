// Playwright for the control app's window. It drives the installed Google Chrome, headless
// (channel "chrome": no browser is downloaded), against panel_server.py --demo by default or
// the mock with PANEL_BACKEND=mock (global-setup.mjs). Results and screenshots go under var/.
//
//   node tools/control-panel/ui-tests/run.mjs            # or, with the repo's Playwright:
//   NODE_PATH=apps/web/node_modules node apps/web/node_modules/@playwright/test/cli.js test \
//     --config tools/control-panel/ui-tests/playwright.config.mjs

const VAR = new URL("../../../var/", import.meta.url).pathname;

export default {
  testDir: ".",
  testMatch: /.*\.spec\.mjs$/,
  outputDir: `${VAR}ui-tests/results`,
  timeout: 45000,
  expect: { timeout: 8000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: `${VAR}ui-tests/report`, open: "never" }]],
  globalSetup: new URL("./global-setup.mjs", import.meta.url).pathname,
  use: {
    channel: "chrome",
    headless: true,
    viewport: { width: 1100, height: 760 },
    colorScheme: "light",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chrome", use: { channel: "chrome" } }],
};
