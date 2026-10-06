// What the specs share: Playwright and axe from the checkout (through NODE_PATH, see run.mjs),
// the helper's address and token from global-setup.mjs, and a way to set the made-up world.

import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";

const require = createRequire(import.meta.url);
export const { test, expect } = require("@playwright/test");
export const AxeBuilder = require("@axe-core/playwright").default;

export const isMock = () => process.env.PANEL_KIND !== "demo";
export const baseUrl = () => process.env.PANEL_URL;
export const token = () => process.env.PANEL_TOKEN;

export const SHOTS = new URL("../../../var/screenshots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

export const VIEWS = [
  ["home", "Home"],
  ["run", "Run"],
  ["data", "Data"],
  ["checks", "Checks"],
  ["features", "Features"],
  ["pipeline", "Pipeline & events"],
  ["flags", "Flags"],
  ["processes", "Processes"],
  ["logs", "Logs"],
  ["commands", "Commands"],
  ["guide", "Guide"],
];

/**
 * Sets the made-up world a spec starts from: POST /api/demo/state on panel_server.py --demo, or
 * POST /__mock/state on the mock. Both take the same body (API.md, section 9): reset, world,
 * failNext, prefs, speed and expireTokens.
 */
export async function setWorld(request, state) {
  const headers = { "X-Panel-Token": token(), "Content-Type": "application/json" };
  const path = isMock() ? "/__mock/state" : "/api/demo/state";
  const response = await request.post(`${baseUrl()}${path}`, { headers, data: state });
  if (!response.ok()) {
    throw new Error(`setting the world failed: ${response.status()} ${await response.text()}`);
  }
}

/**
 * The address a window opens with, the way the app shell makes it: a single-use launch code from
 * POST /api/launch-code (with the token), never the token itself.
 */
export async function launchUrl(request, view = "") {
  const response = await request.post(`${baseUrl()}/api/launch-code`, {
    headers: { "X-Panel-Token": token(), "Content-Type": "application/json" },
    data: {},
  });
  if (!response.ok()) throw new Error(`no launch code: ${response.status()}`);
  const { code } = await response.json();
  return `${baseUrl()}/#launch=${encodeURIComponent(code)}${view ? `&view=${view}` : ""}`;
}

/** Opens the window the way the app shell does, then goes to a view, and waits until it is live. */
export async function openApp(page, view = "home") {
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.goto(await launchUrl(page.request));
  await expect(page.locator(".pill[data-part='docker']")).not.toHaveAttribute(
    "data-state",
    "unknown",
  );
  if (view !== "home") {
    await page.evaluate((v) => (window.location.hash = `#/${v}`), view);
  }
  await expect(page.locator(`.view[data-view='${view}']`)).toBeVisible();
  return errors;
}

/** axe with the WCAG A and AA rules, once the finite animations (a dialog fading in) are done. */
export async function axe(page) {
  await page.waitForFunction(() =>
    document
      .getAnimations()
      .every((a) => a.playState !== "running" || a.effect?.getTiming().iterations === Infinity),
  );
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  return results.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.slice(0, 5).map((n) => n.target.join(" ")),
  }));
}

/** Answers the question a data change may ask (the demo helper's branch is not main). */
export async function confirmIfAsked(page) {
  const dialog = page.getByRole("dialog");
  try {
    await dialog.waitFor({ state: "visible", timeout: 2500 });
  } catch {
    return false;
  }
  const ack = dialog.getByRole("checkbox", { name: /I understand/ });
  if (await ack.count()) await ack.check();
  await dialog.locator(".dialog-footer .btn").last().click();
  await dialog.waitFor({ state: "hidden" });
  return true;
}
