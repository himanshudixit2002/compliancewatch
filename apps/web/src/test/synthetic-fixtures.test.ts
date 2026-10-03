import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Test data is obviously synthetic: "Example ..." text, dates in the year 2000, zero or
 * example identifiers. A fixture that reads like a real return, regulator, business or person
 * can be mistaken for real content and goes stale as the rules change, so the tests and the
 * fixtures of the web app and the UI kit must not name one (docs/web/testing.md, "Synthetic
 * fixtures"). This test reads every test and fixture file and rejects the realistic tokens.
 */
const REPO_ROOT = resolve(__dirname, "../../../..");

/** Where the web app's and the UI kit's tests and fixtures live. */
const ROOTS = ["apps/web/src", "apps/web/e2e", "apps/web/scripts", "packages/ui/src"];

/** Generated or installed trees under the roots. */
const SKIPPED_DIRS = new Set(["node_modules", ".next", "coverage", "test-results"]);

/**
 * Recorded from a real notification with the pipeline's parser and replayed byte for byte by the
 * seed, which hashes the source file (scripts/seed/fixtures/rulebook/README.md): rewriting them
 * would break the replay, so they keep the real text.
 */
const RECORDED = ["apps/web/scripts/seed/fixtures/"];

/** Files that name the tokens in order to reject them, each with its reason. */
const ALLOWED: Readonly<Record<string, string>> = {
  "apps/web/src/test/synthetic-fixtures.test.ts": "this guard's own list of the tokens",
  "apps/web/src/features/design-catalogue/ui/fixtures.test.ts":
    "the catalogue's pattern of the regulatory vocabulary its fixtures must not contain",
};

/** Realistic return and tax names, the regulator, and the stock business and person names. */
const REALISTIC = /\b(?:CBIC|GSTR|CGST|IGST|SGST|Acme|Asha)/i;

/** A test (`*.test.ts(x)`, `*.test.mts`, `*.spec.ts`) or a fixture (by its name or folder). */
function isTestOrFixture(path: string): boolean {
  const name = path.slice(path.lastIndexOf("/") + 1);
  if (/\.(test|spec)\.(tsx?|mts)$/.test(name)) return true;
  return /fixture/i.test(name) || path.includes("/fixtures/");
}

function filesUnder(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (SKIPPED_DIRS.has(entry.name)) return [];
    const path = join(dir, entry.name);
    return entry.isDirectory()
      ? filesUnder(path)
      : [relative(REPO_ROOT, path).split(sep).join("/")];
  });
}

function scanned(): string[] {
  return ROOTS.flatMap((root) => filesUnder(join(REPO_ROOT, root))).filter(
    (path) => isTestOrFixture(path) && !RECORDED.some((prefix) => path.startsWith(prefix)),
  );
}

describe("synthetic fixtures", () => {
  it("knows a test or a fixture by its name or its folder", () => {
    expect(isTestOrFixture("apps/web/src/features/x/ui/view.test.tsx")).toBe(true);
    expect(isTestOrFixture("apps/web/src/server/x.test.ts")).toBe(true);
    expect(isTestOrFixture("apps/web/scripts/seed/seed.test.mts")).toBe(true);
    expect(isTestOrFixture("apps/web/e2e/home.spec.ts")).toBe(true);
    expect(isTestOrFixture("apps/web/src/test/business-fixture.ts")).toBe(true);
    expect(isTestOrFixture("apps/web/e2e/fixtures.ts")).toBe(true);
    expect(isTestOrFixture("apps/web/scripts/seed/fixtures/rulebook/x.json")).toBe(true);
    expect(isTestOrFixture("apps/web/src/features/x/ui/view.tsx")).toBe(false);
  });

  it("matches the realistic tokens in any case, and not inside other words", () => {
    for (const text of ["GSTR-3B", "gstr1", "From CBIC", "cgst", "IGST", "SGST", "Acme", "asha@"]) {
      expect(REALISTIC.test(text), text).toBe(true);
    }
    for (const text of ["Example return 1", "Example regulator", "Kasha", "dasha"]) {
      expect(REALISTIC.test(text), text).toBe(false);
    }
  });

  it("reads tests and fixtures in the web app and the UI kit, and skips the recorded ones", () => {
    const files = scanned();
    expect(files).toContain("apps/web/src/test/rulebook-fixture.ts");
    expect(files).toContain("apps/web/e2e/fixtures.ts");
    expect(files).toContain("apps/web/scripts/seed/seed.test.mts");
    expect(files.some((path) => path.startsWith("packages/ui/src/"))).toBe(true);
    expect(files.some((path) => path.startsWith("apps/web/scripts/seed/fixtures/"))).toBe(false);
  });

  it("finds no realistic token in a test or a fixture", () => {
    const found = scanned()
      .filter((path) => !Object.hasOwn(ALLOWED, path))
      .flatMap((path) =>
        readFileSync(join(REPO_ROOT, path), "utf8")
          .split("\n")
          .flatMap((line, index) => {
            const match = REALISTIC.exec(line);
            return match === null ? [] : [`${path}:${index + 1}: ${match[0]}`];
          }),
      );
    expect(found, "use example text: Example return 1, Example notice 1, the year 2000").toEqual(
      [],
    );
  });

  it("allows only files that still name a token, for a reason", () => {
    for (const [path, reason] of Object.entries(ALLOWED)) {
      expect(reason.trim().length, path).toBeGreaterThan(0);
      expect(REALISTIC.test(readFileSync(join(REPO_ROOT, path), "utf8")), path).toBe(true);
    }
  });
});
