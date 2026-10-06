#!/usr/bin/env node
// Runs the window's Playwright tests with the checkout's own Playwright and axe
// (apps/web/node_modules) and the installed Google Chrome; nothing is downloaded.
//
//   node tools/control-panel/ui-tests/run.mjs [playwright test arguments]
//     against panel_server.py --demo (the real helper, made-up data, its world set through
//     POST /api/demo/state)
//   PANEL_BACKEND=mock node .../run.mjs     # against the mock, offline, without Python
//   node .../run.mjs --both                 # both: the mock, then --demo
//   CW_CONTROL_PANEL_REPO=<checkout> node .../run.mjs   # from a copy outside the checkout

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));

function checkout() {
  const candidates = [];
  if (process.env.CW_CONTROL_PANEL_REPO)
    candidates.push(resolve(process.env.CW_CONTROL_PANEL_REPO));
  let dir = here;
  for (let i = 0; i < 6; i += 1) {
    candidates.push(dir);
    dir = dirname(dir);
  }
  return candidates.find((c) =>
    existsSync(join(c, "apps/web/node_modules/@playwright/test/cli.js")),
  );
}

const repo = checkout();
if (!repo) {
  console.error(
    "Cannot find the checkout's Playwright (apps/web/node_modules). Run pnpm install there, or set CW_CONTROL_PANEL_REPO.",
  );
  process.exit(2);
}
const modules = join(repo, "apps/web/node_modules");
const args = process.argv.slice(2);
const both = args.includes("--both");

function run(backend) {
  const env = { ...process.env, NODE_PATH: modules, PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD: "1" };
  if (backend) env.PANEL_BACKEND = backend;
  const result = spawnSync(
    process.execPath,
    [
      join(modules, "@playwright/test/cli.js"),
      "test",
      "--config",
      join(here, "playwright.config.mjs"),
      ...args.filter((arg) => arg !== "--both"),
    ],
    { stdio: "inherit", env },
  );
  return result.status ?? 1;
}

// --both: the mock first, then the real helper's --demo, whose screenshots are the ones kept
const status = both ? Math.max(run("mock"), run("demo")) : run(process.env.PANEL_BACKEND);
process.exit(status);
