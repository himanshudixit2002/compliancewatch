import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, posix, relative, resolve, sep } from "node:path";
import { describe, expect, it } from "vitest";
import { FLAG_NAMES } from "./flags.ts";
import { ROLES, TENANT_KINDS, isRole } from "./roles.ts";
import {
  SCREENS,
  hrefFor,
  isCatchAll,
  isScreenId,
  isVisibleTo,
  matchScreen,
  routeParams,
  screenById,
  screensFor,
  toRoutePattern,
} from "./screens.ts";
import type { AwaitedRoute, Screen } from "./screens.ts";
import { HTTP_METHODS, SERVICES_WITH_SPECS, isServiceName, routeKey } from "./services.ts";
import type { RouteRef } from "./services.ts";

const APP_DIR = resolve(__dirname, "../../app");
const E2E_DIR = resolve(__dirname, "../../../e2e");
const REPO_ROOT = resolve(__dirname, "../../../../..");
const SPEC_DIR = join(REPO_ROOT, "packages/contracts/openapi");

interface OpenApiDocument {
  paths: Record<string, Record<string, unknown>>;
}

/** Every "service METHOD path" the committed specs offer. */
function committedRoutes(): Set<string> {
  const keys = new Set<string>();
  for (const service of SERVICES_WITH_SPECS) {
    const file = join(SPEC_DIR, `${service}.v1.json`);
    const spec = JSON.parse(readFileSync(file, "utf8")) as OpenApiDocument;
    for (const [path, operations] of Object.entries(spec.paths)) {
      for (const method of Object.keys(operations)) {
        const upper = method.toUpperCase();
        if ((HTTP_METHODS as readonly string[]).includes(upper)) {
          keys.add(routeKey({ service, method: upper as RouteRef["method"], path }));
        }
      }
    }
  }
  return keys;
}

const COMMITTED = committedRoutes();
const isCommitted = (route: RouteRef) => COMMITTED.has(routeKey(route));
const fileExists = (repoPath: string) => existsSync(join(REPO_ROOT, repoPath));

/** Route-group segments "(app)" are stripped: app/(app)/x/page.tsx serves /x. */
function appRoutes(kind: "page.tsx" | "route.ts"): string[] {
  const walk = (dir: string): string[] =>
    readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) return walk(path);
      return entry.name === kind ? [path] : [];
    });
  return walk(APP_DIR).map((file) => {
    const segments = relative(APP_DIR, file)
      .split(sep)
      .slice(0, -1)
      .filter((segment) => !/^\(.*\)$/.test(segment));
    return `/${posix.join(...segments)}`.replace(/^\/\.$/, "/");
  });
}

/** Only pages and handlers own a route file; components and capabilities name a host route. */
function fileForRoute(screen: Screen): boolean {
  if (screen.kind !== "page" && screen.kind !== "handler") return false;
  const name = screen.kind === "handler" ? "route.ts" : "page.tsx";
  return appRoutes(name).includes(screen.route);
}

const pages = SCREENS.filter((screen) => screen.kind === "page");
const byStatus = (status: Screen["status"]) => SCREENS.filter((screen) => screen.status === status);

describe("screen registry", () => {
  it("has unique ids that start with the section, and unique page routes", () => {
    const ids = SCREENS.map((screen) => screen.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const screen of SCREENS) {
      expect(screen.id, screen.id).toMatch(/^[a-z]+(\.[a-z0-9-]+)+$/);
      expect(screen.id.startsWith(`${screen.section}.`), screen.id).toBe(true);
    }
    const routes = pages.map((screen) => screen.route);
    expect(new Set(routes).size).toBe(routes.length);
  });

  it("gives every entry a title, a guide reference, roles and valid references", () => {
    for (const screen of SCREENS) {
      expect(screen.title.trim().length, screen.id).toBeGreaterThan(0);
      expect(screen.guideRef.trim().length, screen.id).toBeGreaterThan(0);
      expect(screen.route.startsWith("/"), screen.id).toBe(true);
      if (screen.roles !== "public") {
        expect(screen.roles.length, screen.id).toBeGreaterThan(0);
        expect(screen.roles.every(isRole), screen.id).toBe(true);
      }
      for (const kind of screen.tenantKinds ?? []) {
        expect(TENANT_KINDS, screen.id).toContain(kind);
      }
      if (screen.flag !== undefined) expect(FLAG_NAMES, screen.id).toContain(screen.flag);
      if (screen.parent !== undefined) {
        expect(isScreenId(screen.parent), `${screen.id} parent ${screen.parent}`).toBe(true);
      }
      for (const route of [...screen.uses, ...screen.awaits]) {
        expect(isServiceName(route.service), screen.id).toBe(true);
        expect(route.path.startsWith("/"), screen.id).toBe(true);
      }
      const awaitKeys = screen.awaits.map(routeKey);
      expect(new Set(awaitKeys).size, screen.id).toBe(awaitKeys.length);
    }
  });

  it("names exactly the services whose spec is committed", () => {
    const stems = readdirSync(SPEC_DIR)
      .filter((name) => name.endsWith(".v1.json"))
      .map((name) => name.slice(0, -".v1.json".length))
      .sort();
    expect(
      [...SERVICES_WITH_SPECS].sort(),
      "SERVICES_WITH_SPECS in services.ts must list the packages/contracts/openapi/*.v1.json stems",
    ).toEqual(stems);
  });

  it("only calls routes that exist in a committed spec", () => {
    for (const screen of SCREENS) {
      for (const route of screen.uses) {
        expect(isCommitted(route), `${screen.id} uses ${routeKey(route)}`).toBe(true);
      }
    }
  });

  it("marks every live page and handler with its file, and its e2e specs exist", () => {
    const e2eExists = existsSync(E2E_DIR);
    for (const screen of byStatus("live")) {
      if (screen.kind === "page" || screen.kind === "handler") {
        expect(fileForRoute(screen), `${screen.id} needs ${screen.route}`).toBe(true);
      }
      if (screen.kind === "page" && e2eExists) {
        expect(screen.e2e.length, `${screen.id} lists no e2e spec`).toBeGreaterThan(0);
      }
      for (const spec of screen.e2e) {
        expect(existsSync(join(E2E_DIR, spec)), `${screen.id} e2e ${spec}`).toBe(true);
      }
    }
  });

  it("keeps waiting entries honest: something absent, present awaits also used, no page", () => {
    for (const screen of byStatus("waiting")) {
      const routes = screen.awaits;
      const files = screen.awaitsFiles ?? [];
      expect(routes.length + files.length, `${screen.id} awaits nothing`).toBeGreaterThan(0);
      const absent = [
        ...routes.filter((route) => !isCommitted(route)),
        ...files.filter((file) => !fileExists(file.path)),
      ];
      expect(absent.length, `backend merged: flip ${screen.id} to live`).toBeGreaterThan(0);
      for (const route of routes.filter(isCommitted)) {
        const used = screen.uses.some((use) => routeKey(use) === routeKey(route));
        expect(used, `${screen.id} awaits present route ${routeKey(route)} without using it`).toBe(
          true,
        );
      }
      expect(fileForRoute(screen), `${screen.id} is waiting but has a route file`).toBe(false);
      expect(
        routes.every((route) => route.owner !== "unplanned"),
        screen.id,
      ).toBe(true);
    }
  });

  it("keeps planned entries honest: awaits from nobody, no page", () => {
    for (const screen of byStatus("planned")) {
      const items: readonly { owner: AwaitedRoute["owner"] }[] = [
        ...screen.awaits,
        ...(screen.awaitsFiles ?? []),
      ];
      expect(items.length, screen.id).toBeGreaterThan(0);
      expect(
        items.every((item) => item.owner === "unplanned"),
        screen.id,
      ).toBe(true);
      expect(fileForRoute(screen), `${screen.id} is planned but has a route file`).toBe(false);
    }
  });

  it("registers every page.tsx and route.ts under src/app exactly once", () => {
    for (const route of appRoutes("page.tsx")) {
      const entries = pages.filter((screen) => screen.route === route);
      expect(entries.length, `page ${route}`).toBe(1);
    }
    for (const route of appRoutes("route.ts")) {
      const entries = SCREENS.filter(
        (screen) => screen.kind === "handler" && screen.route === route,
      );
      expect(entries.length, `handler ${route}`).toBe(1);
    }
  });

  it("marks KAG-track paths unconfirmed until their specs are committed", () => {
    for (const screen of SCREENS) {
      for (const route of screen.awaits) {
        if (route.owner === "plan-k")
          expect(route.unconfirmed, `${screen.id} ${route.path}`).toBe(true);
        if (route.owner === "plan-a")
          expect(route.ref, `${screen.id} ${route.path}`).toMatch(/^WP\d+$/);
      }
    }
  });
});

describe("routes", () => {
  it("extracts parameters and builds patterns for static, dynamic and catch-all routes", () => {
    expect(routeParams("/b/[businessId]/obligations/[obligationId]")).toEqual([
      "businessId",
      "obligationId",
    ]);
    expect(routeParams("/admin/[...slug]")).toEqual(["slug"]);
    expect(isCatchAll("/admin/[...slug]")).toBe(true);
    expect(isCatchAll("/admin/team")).toBe(false);
    expect(toRoutePattern("/settings/team").test("/settings/team")).toBe(true);
    expect(toRoutePattern("/settings/team").test("/settings/team/x")).toBe(false);
    expect(toRoutePattern("/b/[businessId]/ask").test("/b/abc/ask")).toBe(true);
    expect(toRoutePattern("/b/[businessId]/ask").test("/b/a/b/ask")).toBe(false);
    expect(toRoutePattern("/[...slug]").test("/a/b/c")).toBe(true);
  });

  it("matches a pathname to the most specific page and decodes its parameters", () => {
    const match = matchScreen("/b/00000000-0000-4000-8000-000000000001/obligations/ob%201");
    expect(match?.screen.id).toBe("owner.obligation");
    expect(match?.params).toEqual({
      businessId: "00000000-0000-4000-8000-000000000001",
      obligationId: "ob 1",
    });
    expect(matchScreen("/admin/tenants/t1")?.screen.id).toBe("admin.tenant");
    expect(matchScreen("/admin/tenants")?.screen.id).toBe("admin.tenants");
    expect(matchScreen("/admin/review/stats")?.screen.id).toBe("admin.review.stats");
    expect(matchScreen("/admin/review/task-9")?.screen.id).toBe("admin.review.task");
    expect(matchScreen("/settings/team/")?.screen.id).toBe("owner.settings.team");
    expect(matchScreen("/nowhere")).toBeNull();
    expect(matchScreen("/b/x/changes")?.screen.kind).toBe("page");
  });

  it("fills route parameters in hrefFor and refuses a missing one", () => {
    const obligation = screenById("owner.obligation");
    expect(hrefFor(obligation, { businessId: "b1", obligationId: "o/1" })).toBe(
      "/b/b1/obligations/o%2F1",
    );
    expect(hrefFor(screenById("admin.home"))).toBe("/admin");
    expect(() => hrefFor(obligation, { businessId: "b1" })).toThrow(/obligationId/);
  });

  it("filters screens by roles and tenant kind", () => {
    expect(screensFor(null).every((screen) => screen.roles === "public")).toBe(true);
    const owner = screensFor(["owner"], "business").map((screen) => screen.id);
    expect(owner).toContain("owner.changes");
    expect(owner).toContain("system.home");
    expect(owner).not.toContain("admin.home");
    expect(owner).not.toContain("ca.clients");
    expect(isVisibleTo(screenById("owner.evidence"), ["owner"], "ca_firm")).toBe(false);
    expect(isVisibleTo(screenById("owner.evidence"), ["owner"])).toBe(true);
    for (const role of ROLES) {
      expect(screensFor([role]).length, role).toBeGreaterThan(1);
    }
    expect(() => screenById("nope" as never)).toThrow(/unknown screen/);
  });
});
