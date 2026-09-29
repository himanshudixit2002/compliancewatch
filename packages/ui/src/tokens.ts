/**
 * TypeScript mirror of src/styles/tokens.css: the colour role names, the tone vocabulary the
 * components share, and a parser that reads the scheme blocks back out of the CSS so tests can
 * check the file rather than a copy of it.
 */

export const COLOR_TOKENS = [
  "bg",
  "surface",
  "surface-raised",
  "fg",
  "fg-muted",
  "line",
  "line-strong",
  "primary",
  "primary-fg",
  "accent",
  "accent-fg",
  "success",
  "success-fg",
  "warning",
  "warning-fg",
  "danger",
  "danger-fg",
  "info",
  "info-fg",
  "focus",
] as const;

export type ColorToken = (typeof COLOR_TOKENS)[number];

/** Status vocabulary shared by Badge, StatusChip, Banner and Timeline. */
export const TONES = ["neutral", "success", "warning", "danger", "info"] as const;

export type Tone = (typeof TONES)[number];

export const TYPE_SCALE = ["xs", "sm", "base", "lg", "xl", "2xl", "3xl"] as const;

export const RADII = ["sm", "md", "lg"] as const;

export type ColorScheme = "light" | "dark";

/** The three selectors that carry colour tokens in tokens.css. */
export const SCHEME_SELECTORS = {
  light: ":root",
  dark: ".dark",
  /** The prefers-color-scheme fallback; must declare the same values as `.dark`. */
  darkMedia: ":root:not(.light)",
} as const;

const DECLARATION = /--([a-z0-9*-]+)\s*:\s*([^;]+);/g;

/**
 * Reads the `--name: value;` declarations of the first block that starts with `selector {`.
 * Token blocks never nest, so the block ends at the first closing brace.
 */
export function parseTokenBlock(css: string, selector: string): Record<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start === -1) {
    throw new Error(`tokens.css has no "${selector}" block`);
  }
  const bodyStart = start + selector.length + 2;
  const end = css.indexOf("}", bodyStart);
  const body = css.slice(bodyStart, end);
  const tokens: Record<string, string> = {};
  for (const match of body.matchAll(DECLARATION)) {
    tokens[match[1] as string] = (match[2] as string).trim();
  }
  return tokens;
}

/** The light and dark colour tokens as declared in tokens.css. */
export function parseTokens(css: string): Record<ColorScheme, Record<string, string>> {
  return {
    light: parseTokenBlock(css, SCHEME_SELECTORS.light),
    dark: parseTokenBlock(css, SCHEME_SELECTORS.dark),
  };
}
