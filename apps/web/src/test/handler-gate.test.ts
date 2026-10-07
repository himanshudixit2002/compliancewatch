// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { posix, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";
import { SCREENS } from "@/shared/config/screens";
import { handlerGateProblems, routeOf, type RouteFile } from "./handler-gate";

const SRC = posix.join(__dirname.split(sep).join("/"), "..");

/** Every route.ts under the directory, as paths relative to src. */
function routeFiles(dir: string): RouteFile[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = posix.join(dir, entry.name);
    if (entry.isDirectory()) return routeFiles(path);
    if (entry.name !== "route.ts") return [];
    return [{ path: relative(SRC, path).split(sep).join("/"), source: readFileSync(path, "utf8") }];
  });
}

/** The registry's handler entry for a route. */
function handlerFor(route: string): string | undefined {
  return SCREENS.find((screen) => screen.kind === "handler" && screen.route === route)?.id;
}

const PATH = "app/api-bff/pipeline/sources/[key]/uploads/route.ts";

const GATED = `
import type { NextRequest } from "next/server";
import { gateHandler } from "@/server/bff/gate";
import { uploadResponse } from "@/server/bff/upload";
import { screenById } from "@/shared/config/screens";

export const dynamic = "force-dynamic";

const SCREEN = screenById("system.uploads");

export async function POST(request: NextRequest, { params }: Context): Promise<Response> {
  const gate = await gateHandler(SCREEN, request);
  if (!gate.ok) return gate.response;
  const { key } = await params;
  return uploadResponse(request, key, gate.session);
}
`;

function check(source: string, path = PATH): string[] {
  return handlerGateProblems({ path, source }, handlerFor);
}

describe("handlerGateProblems", () => {
  it("passes a handler that runs the gate with its route's entry first", () => {
    expect(check(GATED)).toEqual([]);
    const inline = GATED.replace(
      "gateHandler(SCREEN,",
      'gateHandler(screenById("system.uploads"),',
    );
    expect(check(inline)).toEqual([]);
    const block = GATED.replace(
      "if (!gate.ok) return gate.response;",
      "if (!gate.ok) {\n    return gate.response;\n  }",
    );
    expect(check(block)).toEqual([]);
  });

  it("names the file when anything runs before the gate", () => {
    const late = GATED.replace(
      "  const gate = await gateHandler(SCREEN, request);",
      "  const { key } = await params;\n  const gate = await gateHandler(SCREEN, request);",
    );
    expect(check(late)).toEqual([
      expect.stringMatching(new RegExp(`^${escape(PATH)}: POST must start with`)),
    ]);
    const unchecked = GATED.replace("  if (!gate.ok) return gate.response;\n", "");
    expect(check(unchecked)).toHaveLength(1);
    const otherRequest = GATED.replace(
      "gateHandler(SCREEN, request)",
      "gateHandler(SCREEN, other)",
    );
    expect(check(otherRequest)).toHaveLength(1);
  });

  it("names the file when the gate is not the shared one or not given the route's entry", () => {
    const local = GATED.replace('from "@/server/bff/gate"', 'from "./my-gate"');
    expect(check(local)).toEqual([expect.stringContaining("imported from @/server/bff/gate")]);
    const wrong = GATED.replace(
      'screenById("system.uploads")',
      'screenById("system.raw-document")',
    );
    expect(check(wrong)).toEqual([
      `${PATH}: POST gates with the entry system.raw-document, but the route is system.uploads's`,
    ]);
    const unknown = GATED.replace("gateHandler(SCREEN,", "gateHandler(SOMETHING,");
    expect(check(unknown)).toHaveLength(1);
  });

  it("names the file for a method exported another way, no method, or a route the registry lacks", () => {
    const arrow = `${GATED}\nexport const GET = async () => new Response(null);\n`;
    expect(check(arrow)).toEqual([
      `${PATH}: GET must be exported as a function declaration that runs the gate first`,
    ]);
    const reexport = `${GATED}\nexport { POST as PUT };\n`;
    expect(check(reexport)).toHaveLength(1);
    expect(check('export const dynamic = "force-dynamic";')).toEqual([
      `${PATH}: exports no HTTP method`,
    ]);
    const stray = "app/api-bff/example/route.ts";
    expect(check(GATED, stray)).toEqual([
      `${stray}: no handler entry of the screen registry has the route /api-bff/example`,
    ]);
  });

  it("reads a route from its file, route groups left out", () => {
    expect(routeOf(PATH)).toBe("/api-bff/pipeline/sources/[key]/uploads");
    expect(routeOf("app/(group)/api-bff/x/route.ts")).toBe("/api-bff/x");
  });
});

describe("app/api-bff", () => {
  it("runs the shared gate with the registry entry before anything else in every handler", () => {
    const files = routeFiles(posix.join(SRC, "app/api-bff"));
    expect(files.length).toBeGreaterThan(0);
    expect(files.flatMap((file) => handlerGateProblems(file, handlerFor))).toEqual([]);
  });
});

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
