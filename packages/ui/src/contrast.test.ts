import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  AA_TEXT,
  AA_UI,
  TEXT_PAIRS,
  UI_PAIRS,
  checkContrast,
  contrastRatio,
  relativeLuminance,
} from "./contrast";
import { parseTokens } from "./tokens";

const css = readFileSync(join(__dirname, "styles", "tokens.css"), "utf8");
const schemes = parseTokens(css);

describe("contrastRatio", () => {
  it("matches the WCAG reference values", () => {
    expect(contrastRatio("#000000", "#ffffff")).toBe(21);
    expect(contrastRatio("#ffffff", "#ffffff")).toBe(1);
    expect(contrastRatio("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });

  it("is symmetric and accepts short hex", () => {
    expect(contrastRatio("#fff", "#000")).toBe(contrastRatio("#000000", "#ffffff"));
    expect(relativeLuminance("#fff")).toBe(1);
    expect(relativeLuminance("#000")).toBe(0);
  });

  it("rejects values that are not hex colours", () => {
    expect(() => relativeLuminance("white")).toThrow("not a hex colour");
    expect(() => contrastRatio("#12345", "#000")).toThrow("not a hex colour");
  });
});

describe.each(["light", "dark"] as const)("%s scheme", (scheme) => {
  const results = checkContrast(schemes[scheme]);

  it(`gives every text pair at least ${AA_TEXT}:1`, () => {
    const failures = results
      .filter((r) => r.minimum === AA_TEXT && !r.ok)
      .map((r) => `${r.foreground} on ${r.background}: ${r.ratio.toFixed(2)}`);
    expect(failures).toEqual([]);
    expect(results.filter((r) => r.minimum === AA_TEXT)).toHaveLength(TEXT_PAIRS.length);
  });

  it(`gives every UI pair at least ${AA_UI}:1`, () => {
    const failures = results
      .filter((r) => r.minimum === AA_UI && !r.ok)
      .map((r) => `${r.foreground} on ${r.background}: ${r.ratio.toFixed(2)}`);
    expect(failures).toEqual([]);
    expect(results.filter((r) => r.minimum === AA_UI)).toHaveLength(UI_PAIRS.length);
  });
});

describe("checkContrast", () => {
  it("reports a failing pair instead of hiding it", () => {
    const flat = Object.fromEntries(Object.keys(schemes.light).map((k) => [k, "#808080"]));
    const results = checkContrast(flat);
    expect(results.every((r) => r.ratio === 1 && !r.ok)).toBe(true);
  });

  it("throws when a pair names a token the scheme lacks", () => {
    expect(() => checkContrast({ bg: "#ffffff" })).toThrow("missing token");
  });
});
