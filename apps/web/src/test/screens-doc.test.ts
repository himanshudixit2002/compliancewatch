import { readdirSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  OUTPUT_PATH,
  SPEC_DIR,
  auditAwaits,
  committedRoutes,
  formatScreensDoc,
  readyEntries,
  renderAudit,
  renderScreensDoc,
  rolesCell,
  waitsForCell,
} from "../../scripts/screens-doc.mts";
import { SCREENS, screenById } from "../shared/config/screens.ts";
import type { Screen } from "../shared/config/screens.ts";
import { routeKey } from "../shared/config/services.ts";

describe("generated screen docs", () => {
  it("docs/web/screens.md is what the generator writes", async () => {
    const expected = await formatScreensDoc(renderScreensDoc());
    const committed = readFileSync(OUTPUT_PATH, "utf8");
    expect(committed, "run: pnpm --filter web screens:gen").toBe(expected);
  });

  it("renders one row per entry in the section tables and in the role matrix", () => {
    const markdown = renderScreensDoc();
    for (const screen of SCREENS) {
      const rows = markdown.split("\n").filter((line) => line.startsWith(`| \`${screen.id}\` |`));
      expect(rows.length, screen.id).toBe(2);
    }
    expect(markdown).toContain(`${SCREENS.length} entries`);
    expect(markdown).toContain("## Roles by screen");
  });

  it("shows flags, awaited routes with their owner and unconfirmed paths", () => {
    const sitemap = screenById("system.sitemap");
    expect(rolesCell(sitemap)).toBe("public");
    expect(waitsForCell(sitemap)).toBe("");
    const stats = screenById("admin.review.stats");
    expect(waitsForCell(stats)).toBe(
      "`GET /v1/rulebook/review/stats` (KAG track, path unconfirmed)",
    );
    const flagged: Screen = { ...sitemap, roles: ["owner", "staff"], flag: "web.qa_enabled" };
    expect(rolesCell(flagged)).toBe("owner, staff; flag `web.qa_enabled`");
    const withFile = SCREENS.find((screen) => (screen.awaitsFiles ?? []).length > 0);
    expect(withFile).toBeDefined();
    if (withFile !== undefined) expect(waitsForCell(withFile)).toContain("`file ");
  });
});

/** The services with a committed spec, read from the directory the audit reads. */
const servicesWithSpec = readdirSync(SPEC_DIR)
  .filter((name) => name.endsWith(".v1.json"))
  // public.v1.json is the merged public facade; its operations belong to the services.
  .filter((name) => name !== "public.v1.json")
  .map((name) => name.slice(0, -".v1.json".length));

describe("awaits audit", () => {
  it("lists awaited routes absent from the committed specs, sorted by service and path", () => {
    const stats = screenById("admin.review.stats");
    const rows = auditAwaits(SCREENS, committedRoutes());
    const statsRow = rows.find((row) => row.screenId === stats.id);
    expect(statsRow).toMatchObject({
      service: "rulebook",
      method: "GET",
      path: "/v1/rulebook/review/stats",
      unconfirmed: true,
      specExists: true,
    });
    const sorted = [...rows].sort(
      (a, b) => a.service.localeCompare(b.service) || a.path.localeCompare(b.path),
    );
    expect(rows.map((row) => `${row.service} ${row.path}`)).toEqual(
      sorted.map((row) => `${row.service} ${row.path}`),
    );
    expect(servicesWithSpec.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.specExists, `${row.service} ${row.path}`).toBe(
        servicesWithSpec.includes(row.service),
      );
    }
  });

  it("drops a route once it is committed", () => {
    const stats = screenById("admin.review.stats");
    const route = stats.awaits[0];
    expect(route).toBeDefined();
    if (route === undefined) return;
    const rows = auditAwaits([stats], new Set([routeKey(route)]));
    expect(rows).toEqual([]);
    const text = renderAudit(auditAwaits([stats], new Set()));
    expect(text).toContain("1 awaited routes are absent");
    expect(text).toContain("[unconfirmed]");
    expect(text).toContain("0 entries are ready");
  });

  it("lists the ready entries as ready with what they will use", () => {
    const ready = readyEntries();
    expect(ready.map((row) => row.screenId)).toContain("admin.flags");
    expect(ready.find((row) => row.screenId === "admin.flags")?.items).toEqual([
      "file packages/flags/registry.json",
    ]);
    const flags = screenById("admin.flags");
    const withUses: Screen = {
      ...flags,
      uses: [{ service: "profile", method: "GET", path: "/v1/ontology" }],
      awaits: [{ service: "profile", method: "GET", path: "/v1/ontology", owner: "plan-a" }],
      awaitsFiles: [],
    };
    expect(readyEntries([withUses, screenById("admin.review.stats")])).toEqual([
      { screenId: "admin.flags", items: ["GET /v1/ontology"] },
    ]);
    const text = renderAudit([], readyEntries([flags]));
    expect(text).toContain("1 entries are ready");
    expect(text).toContain("  admin.flags ready: file packages/flags/registry.json");
  });
});
