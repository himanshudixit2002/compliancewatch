import { readdirSync, readFileSync } from "node:fs";
import { posix, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";
import { isScreenId, screenById } from "@/shared/config/screens";
import {
  PARKED_FEATURES,
  checkFile,
  checkTree,
  featuresImportedByApp,
  importRefs,
  isClientModule,
  layerOf,
  moduleRootOf,
  parkedFolderProblems,
  resolveInternal,
  type ParkedFolderCheck,
  type SourceFile,
} from "./architecture";

const SRC = posix.join(__dirname.split(sep).join("/"), "..");

function sourceFiles(dir: string): SourceFile[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = posix.join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "test" ? [] : sourceFiles(path);
    if (!/\.(ts|tsx|mts)$/.test(entry.name) || /\.(test\.tsx?|d\.ts)$/.test(entry.name)) return [];
    return [{ path: relative(SRC, path).split(sep).join("/"), source: readFileSync(path, "utf8") }];
  });
}

const file = (path: string, source: string): SourceFile => ({ path, source });

describe("layerOf", () => {
  it("names the top-level layer and treats files at the src root as root", () => {
    expect(layerOf("app/page.tsx")).toBe("app");
    expect(layerOf("features/home/ui/home-view.tsx")).toBe("features");
    expect(layerOf("entities/screen/types.ts")).toBe("entities");
    expect(layerOf("server/legal.ts")).toBe("server");
    expect(layerOf("shared/lib/dates.ts")).toBe("shared");
    expect(layerOf("test/setup.ts")).toBe("test");
    expect(layerOf("proxy.ts")).toBe("root");
    expect(layerOf("features")).toBe("root");
  });

  it("identifies the feature or entity directory", () => {
    expect(moduleRootOf("features/home/ui/view.tsx")).toBe("features/home");
    expect(moduleRootOf("entities/screen/mappers.ts")).toBe("entities/screen");
    expect(moduleRootOf("shared/lib/dates.ts")).toBeUndefined();
  });
});

describe("importRefs", () => {
  it("collects static, type-only, side-effect, re-export and dynamic specifiers", () => {
    const refs = importRefs(`
      import "server-only";
      import type { A } from "./a";
      import { b, type C } from "@/shared/b";
      export { d } from "../d";
      export type { E } from "./e";
      const f = await import("./f");
      /* import { g } from "./commented"; */
      // import { h } from "./line-commented";
    `);
    expect(refs).toEqual([
      { specifier: "./a", typeOnly: true },
      { specifier: "@/shared/b", typeOnly: false },
      { specifier: "../d", typeOnly: false },
      { specifier: "./e", typeOnly: true },
      { specifier: "server-only", typeOnly: false },
      { specifier: "./f", typeOnly: false },
    ]);
  });

  it("detects the use client directive after comments", () => {
    expect(isClientModule('"use client";\nimport x from "y";')).toBe(true);
    expect(isClientModule("// note\n'use client'\n")).toBe(true);
    expect(isClientModule('import x from "y";\n"use client";')).toBe(false);
  });
});

describe("resolveInternal", () => {
  it("resolves the @ alias and relative paths against src and drops code extensions", () => {
    expect(resolveInternal("app/page.tsx", "@/features/home")).toBe("features/home");
    expect(resolveInternal("features/home/ui/view.tsx", "../model/labels.ts")).toBe(
      "features/home/model/labels",
    );
    expect(resolveInternal("shared/config/nav.ts", "./roles.ts")).toBe("shared/config/roles");
    expect(resolveInternal("app/page.tsx", "react")).toBeNull();
    expect(resolveInternal("app/page.tsx", "@compliancewatch/ui")).toBeNull();
  });
});

describe("checkFile", () => {
  it("lets app import features, shared, entities and server", () => {
    const source = `
      import { HomeView } from "@/features/home";
      import { t } from "@/shared/i18n";
      import { toScreenLink } from "@/entities/screen/mappers";
      import { requireRole } from "@/server/dal";
      import { Badge } from "@compliancewatch/ui";
      import "./globals.css";
    `;
    expect(checkFile(file("app/page.tsx", source))).toEqual([]);
  });

  it("stops app importing app", () => {
    const [violation] = checkFile(file("app/page.tsx", 'import { x } from "./admin/page";'));
    expect(violation?.reason).toBe("app must not import app");
  });

  it("lets a feature import itself but not another feature or app", () => {
    const own = 'import { x } from "../model/x";\nimport { y } from "@/features/home/ui/y";';
    expect(checkFile(file("features/home/ui/view.tsx", own))).toEqual([]);
    const other = 'import { z } from "@/features/sitemap";';
    expect(checkFile(file("features/home/ui/view.tsx", other))[0]?.reason).toBe(
      "a feature must not import another feature",
    );
    const app = 'import { P } from "@/app/page";';
    expect(checkFile(file("features/home/index.ts", app))[0]?.reason).toBe(
      "features must not import app",
    );
  });

  it("keeps entities pure", () => {
    expect(
      checkFile(
        file(
          "entities/screen/mappers.ts",
          'import type { Screen } from "./types";\nimport { humanise } from "@/shared/lib/humanise";',
        ),
      ),
    ).toEqual([]);
    expect(
      checkFile(file("entities/screen/mappers.ts", 'import { t } from "@/shared/i18n";'))[0]
        ?.reason,
    ).toBe("entities import shared/lib and themselves only");
    expect(
      checkFile(file("entities/screen/mappers.ts", 'import { useState } from "react";'))[0]?.reason,
    ).toBe("entities are pure: no React, next or UI imports");
    expect(
      checkFile(
        file("entities/screen/mappers.ts", 'import { a } from "@/entities/other/types";'),
      )[0]?.reason,
    ).toBe("entities import shared/lib and themselves only");
  });

  it("requires server modules to start with server-only and never import features", () => {
    expect(
      checkFile(
        file(
          "server/legal.ts",
          '// reads docs/legal\nimport "server-only";\nimport { readFileSync } from "node:fs";',
        ),
      ),
    ).toEqual([]);
    const missing = checkFile(file("server/legal.ts", 'import { readFileSync } from "node:fs";'));
    expect(missing[0]?.reason).toBe('server modules start with import "server-only"');
    const feature = checkFile(
      file("server/dal.ts", 'import "server-only";\nimport { x } from "@/features/home";'),
    );
    expect(feature[0]?.reason).toBe("server must not import features");
  });

  it("keeps shared isomorphic", () => {
    expect(checkFile(file("shared/config/nav.ts", 'import { ROLES } from "./roles.ts";'))).toEqual(
      [],
    );
    expect(
      checkFile(file("shared/lib/dates.ts", 'import { cookies } from "next/headers";'))[0]?.reason,
    ).toBe("shared code is isomorphic");
    expect(
      checkFile(file("shared/lib/dates.ts", 'import { readFileSync } from "node:fs";'))[0]?.reason,
    ).toBe("shared code is isomorphic");
    expect(
      checkFile(file("shared/ui/x.tsx", 'import { getEnv } from "@/server/env";'))[0]?.reason,
    ).toBe("shared must not import server");
  });

  it("lets root files such as proxy.ts import server and shared", () => {
    expect(
      checkFile(
        file(
          "proxy.ts",
          'import { ipInCidr } from "@/server/cidr";\nimport { x } from "@/shared/lib/url";',
        ),
      ),
    ).toEqual([]);
    expect(checkFile(file("proxy.ts", 'import { x } from "@/features/home";'))[0]?.reason).toBe(
      "root must not import features",
    );
  });

  it("limits client components to shared, entities and their own directory", () => {
    const ok =
      '"use client";\nimport { t } from "@/shared/i18n";\nimport { Section } from "./sections/buttons";\nimport { Button } from "@compliancewatch/ui";';
    expect(checkFile(file("features/design-catalogue/ui/catalogue.tsx", ok))).toEqual([]);
    const gateway = '"use client";\nimport { homeGateway } from "../gateway";';
    expect(checkFile(file("features/home/ui/form.tsx", gateway))[0]?.reason).toBe(
      "client components import shared, entities and their own directory only",
    );
  });

  it("requires type-only imports of the contracts package", () => {
    expect(
      checkFile(
        file(
          "features/x/ports.ts",
          'import type { paths } from "@compliancewatch/contracts/openapi/profile";',
        ),
      ),
    ).toEqual([]);
    expect(
      checkFile(
        file("features/x/gateway.ts", 'import { paths } from "@compliancewatch/contracts";'),
      )[0]?.reason,
    ).toBe("contracts are imported type-only");
  });

  it("ignores test utilities", () => {
    expect(checkFile(file("test/setup.ts", 'import { x } from "@/app/page";'))).toEqual([]);
  });

  it("reports every violation in a tree", () => {
    const tree = checkTree([
      file("shared/a.ts", 'import { b } from "@/server/b";'),
      file("server/b.ts", 'import "server-only";'),
    ]);
    expect(tree.map((v) => v.file)).toEqual(["shared/a.ts"]);
  });
});

describe("apps/web/src", () => {
  it("follows the layer rules", () => {
    const files = sourceFiles(SRC);
    expect(files.length).toBeGreaterThan(0);
    expect(checkTree(files)).toEqual([]);
  });
});

describe("parked feature folders", () => {
  const statuses: Record<string, string> = { "x.live": "live", "x.ready": "ready" };
  const base: ParkedFolderCheck = {
    folders: ["home", "parked"],
    imported: new Set(["home"]),
    parked: { parked: ["x.ready"] },
    statusOf: (id) => statuses[id],
  };

  it("finds the feature folders a route file imports, and only those", () => {
    const imported = featuresImportedByApp([
      file("app/page.tsx", 'import { HomeView } from "@/features/home";'),
      file("app/b/page.tsx", 'import { a } from "@/features/business/ui/a";\nimport "./x.css";'),
      file("app/c/page.tsx", 'import { t } from "@/shared/i18n";'),
      file("features/sitemap/index.ts", 'import { r } from "@/features/sitemap/model/rows";'),
      file("test/x.ts", 'import { s } from "@/features/settings";'),
    ]);
    expect([...imported].sort()).toEqual(["business", "home"]);
  });

  it("accepts a folder parked for screens that are not live", () => {
    expect(parkedFolderProblems(base)).toEqual([]);
  });

  it("fails on a folder no route file imports that is not parked", () => {
    expect(parkedFolderProblems({ ...base, folders: [...base.folders, "orphan"] })).toEqual([
      "features/orphan: no route file imports it and it is not parked",
    ]);
  });

  it("fails while a parked screen is live and its folder is still not imported", () => {
    expect(parkedFolderProblems({ ...base, parked: { parked: ["x.ready", "x.live"] } })).toEqual([
      "features/parked: x.live is live, but no route file imports the folder",
    ]);
  });

  it("fails on a parked screen the registry does not hold, and on a folder parked for none", () => {
    expect(parkedFolderProblems({ ...base, parked: { parked: ["x.gone"] } })).toEqual([
      "features/parked: parked for x.gone, which the registry does not hold",
    ]);
    expect(parkedFolderProblems({ ...base, parked: { parked: [] } })).toEqual([
      "features/parked: parked for no screen",
    ]);
  });

  it("fails on an entry whose folder a page now imports, or that no longer exists", () => {
    expect(parkedFolderProblems({ ...base, imported: new Set(["home", "parked"]) })).toEqual([
      "features/parked: a route file imports it, so it is no longer parked",
    ]);
    expect(parkedFolderProblems({ ...base, folders: ["home"] })).toEqual([
      "features/parked: parked, but the folder does not exist",
    ]);
  });

  it("parks every folder of apps/web/src/features that no route file imports", () => {
    const folders = readdirSync(posix.join(SRC, "features"), { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name);
    const problems = parkedFolderProblems({
      folders,
      imported: featuresImportedByApp(sourceFiles(SRC)),
      parked: PARKED_FEATURES,
      statusOf: (id) => (isScreenId(id) ? screenById(id).status : undefined),
    });
    expect(problems).toEqual([]);
  });
});
