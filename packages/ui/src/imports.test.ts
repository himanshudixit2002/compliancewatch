import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The package is consumed from source by Next, tsc and vitest, each with its own resolver, so
 * internal imports are relative: never the app's "@/" alias and never the package's own name.
 */
function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.(ts|tsx)$/.test(entry.name) ? [path] : [];
  });
}

describe("internal imports", () => {
  it("are relative paths, not aliases", () => {
    const offenders = sourceFiles(__dirname).filter((file) => {
      const source = readFileSync(file, "utf8");
      return /from\s+["'](@\/|@compliancewatch\/ui)/.test(source);
    });
    expect(offenders).toEqual([]);
  });
});
