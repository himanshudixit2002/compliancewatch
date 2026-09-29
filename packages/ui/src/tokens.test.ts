import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  COLOR_TOKENS,
  RADII,
  SCHEME_SELECTORS,
  TYPE_SCALE,
  parseTokenBlock,
  parseTokens,
} from "./tokens";

const css = readFileSync(join(__dirname, "styles", "tokens.css"), "utf8");

describe("tokens.css", () => {
  it("declares exactly the mirrored colour tokens in the light and dark schemes", () => {
    const { light, dark } = parseTokens(css);
    expect(Object.keys(light).sort()).toEqual([...COLOR_TOKENS].sort());
    expect(Object.keys(dark).sort()).toEqual([...COLOR_TOKENS].sort());
  });

  it("keeps the prefers-color-scheme block identical to the .dark block", () => {
    const { dark } = parseTokens(css);
    expect(parseTokenBlock(css, SCHEME_SELECTORS.darkMedia)).toEqual(dark);
  });

  it("writes every colour token as a six digit hex value", () => {
    const { light, dark } = parseTokens(css);
    for (const value of [...Object.values(light), ...Object.values(dark)]) {
      expect(value).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("maps every colour token onto a Tailwind colour and removes the default palette", () => {
    const theme = parseTokenBlock(css, "@theme inline");
    expect(theme["color-*"]).toBe("initial");
    for (const token of COLOR_TOKENS) {
      expect(theme[`color-${token}`]).toBe(`var(--${token})`);
    }
  });

  it("declares the type scale with a line height per step and the three radii", () => {
    const theme = parseTokenBlock(css, "@theme");
    for (const step of TYPE_SCALE) {
      expect(theme[`text-${step}`]).toMatch(/rem$/);
      expect(theme[`text-${step}--line-height`]).toMatch(/rem$/);
    }
    for (const radius of RADII) {
      expect(theme[`radius-${radius}`]).toMatch(/rem$/);
    }
    expect(theme["font-sans"]).toContain("system-ui");
    expect(theme["font-mono"]).toContain("monospace");
  });
});

describe("parseTokenBlock", () => {
  it("reads declarations from the named block only", () => {
    const sample = ":root {\n  --a: #fff;\n}\n.dark {\n  --a: #000;\n  --b: 1rem;\n}\n";
    expect(parseTokenBlock(sample, ":root")).toEqual({ a: "#fff" });
    expect(parseTokenBlock(sample, ".dark")).toEqual({ a: "#000", b: "1rem" });
  });

  it("throws when the block is missing", () => {
    expect(() => parseTokenBlock(":root {}", ".dark")).toThrow('no ".dark" block');
  });
});
