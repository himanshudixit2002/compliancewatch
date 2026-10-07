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
import { requiredHeaderKey, routeKey } from "../shared/config/services.ts";

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
    const reports = screenById("admin.error-reports");
    expect(waitsForCell(reports)).toBe(
      "`GET /v1/rulebook/error-reports` (services track, WP24); `POST /v1/rulebook/error-reports/{report_id}/decision` (services track, WP24)",
    );
    expect(waitsForCell(screenById("admin.review.stats"))).toBe("");
    const unconfirmed: Screen = {
      ...reports,
      awaits: [
        {
          service: "rulebook",
          method: "GET",
          path: "/v1/rulebook/example",
          owner: "plan-k",
          unconfirmed: true,
        },
      ],
    };
    expect(waitsForCell(unconfirmed)).toBe(
      "`GET /v1/rulebook/example` (KAG track, path unconfirmed)",
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
    const reports = screenById("admin.error-reports");
    const rows = auditAwaits(SCREENS, committedRoutes());
    const reportsRow = rows.find((row) => row.screenId === reports.id);
    expect(reportsRow).toMatchObject({
      service: "rulebook",
      method: "GET",
      path: "/v1/rulebook/error-reports",
      owner: "services track, WP24",
      unconfirmed: false,
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

  it("keeps a hardened route listed until a spec requires its header", () => {
    const resend = screenById("admin.notification.resend");
    expect(waitsForCell(resend)).toBe(
      "`POST /v1/notification/notifications/{notification_id}/resend` with `Idempotency-Key` (services track, WP30)",
    );
    const route = resend.awaits[0];
    expect(route).toBeDefined();
    if (route === undefined) return;
    const committed = committedRoutes();
    expect(committed.has(routeKey(route))).toBe(true);
    expect(auditAwaits([resend], committed)).toEqual([
      {
        screenId: resend.id,
        service: "notification",
        method: "POST",
        path: "/v1/notification/notifications/{notification_id}/resend",
        header: "Idempotency-Key",
        owner: "services track, WP30",
        unconfirmed: false,
        specExists: true,
      },
    ]);
    expect(renderAudit(auditAwaits([resend], committed))).toContain(
      "notification POST /v1/notification/notifications/{notification_id}/resend with Idempotency-Key <- admin.notification.resend",
    );
    const hardened = new Set([...committed, requiredHeaderKey(route, "Idempotency-Key")]);
    expect(auditAwaits([resend], hardened)).toEqual([]);
  });

  it("drops a route once it is committed", () => {
    const reports = screenById("admin.error-reports");
    const route = reports.awaits[0];
    expect(route).toBeDefined();
    if (route === undefined) return;
    const rows = auditAwaits([{ ...reports, awaits: [route] }], new Set([routeKey(route)]));
    expect(rows).toEqual([]);
    // A path the design named before its spec was committed is marked as unconfirmed.
    const unconfirmed: Screen = {
      ...reports,
      awaits: [{ ...route, owner: "plan-k", unconfirmed: true }],
    };
    const text = renderAudit(auditAwaits([unconfirmed], new Set()));
    expect(text).toContain("1 awaited routes are absent");
    expect(text).toContain("(1 with an unconfirmed path)");
    expect(text).toContain("[unconfirmed]");
    expect(text).toContain("0 entries are ready");
  });

  it("lists the ready entries as ready with what they will use", () => {
    const ready = readyEntries();
    expect(ready.map((row) => row.screenId)).toContain("admin.evals.run");
    expect(ready.find((row) => row.screenId === "admin.evals.run")?.items).toEqual([
      "GET /v1/eval/runs/{run_id}",
    ]);
    const run = screenById("admin.evals.run");
    const withFile: Screen = {
      ...run,
      awaitsFiles: [{ path: "packages/example/registry.json", owner: "plan-a", ref: "WP12" }],
    };
    const withAwait: Screen = {
      ...run,
      uses: [{ service: "profile", method: "GET", path: "/v1/ontology" }],
      awaits: [{ service: "profile", method: "GET", path: "/v1/ontology", owner: "plan-a" }],
    };
    expect(readyEntries([withAwait, screenById("admin.error-reports")])).toEqual([
      { screenId: "admin.evals.run", items: ["GET /v1/ontology"] },
    ]);
    const text = renderAudit([], readyEntries([withFile]));
    expect(text).toContain("1 entries are ready");
    expect(text).toContain(
      "  admin.evals.run ready: file packages/example/registry.json; GET /v1/eval/runs/{run_id}",
    );
  });
});
