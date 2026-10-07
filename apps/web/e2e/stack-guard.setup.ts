import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test as setup } from "@playwright/test";

/**
 * The default project's guard: the chromium project depends on this one, so it runs before any
 * spec, whether make web-e2e started the run (which ran the same check before its build) or
 * Playwright was run directly. The specs stage synthetic data through the services, so they run
 * only against a memory stack that make web-stack recorded, or with E2E_ALLOW_POSTGRES=1
 * (scripts/stack-guard/lib.mts). The product project, against make product, depends on nothing
 * and stages none of this.
 */
setup("the services are a memory web stack, or the run is allowed onto them", () => {
  const script = resolve(__dirname, "../scripts/stack-guard/main.mts");
  const guard = spawnSync(
    process.execPath,
    ["--disable-warning=MODULE_TYPELESS_PACKAGE_JSON", script],
    { encoding: "utf8" },
  );
  const said = `${guard.stderr ?? ""}${guard.stdout ?? ""}`.trim();
  if (guard.status !== 0) {
    throw new Error(said || `the stack guard ended with ${guard.status ?? guard.signal}`);
  }
  if (said !== "") console.log(said);
});
