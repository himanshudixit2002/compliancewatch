import type { ColorToken } from "./tokens";

/** Pairs rendered as text on a background: WCAG AA needs 4.5:1. */
export const TEXT_PAIRS: readonly (readonly [text: ColorToken, background: ColorToken])[] = [
  ["fg", "bg"],
  ["fg-muted", "bg"],
  ["fg", "surface"],
  ["fg-muted", "surface"],
  ["fg", "surface-raised"],
  ["fg-muted", "surface-raised"],
  ["primary-fg", "primary"],
  ["accent-fg", "accent"],
  ["success-fg", "success"],
  ["warning-fg", "warning"],
  ["danger-fg", "danger"],
  ["info-fg", "info"],
  // Tone colours are also used as text (links, error text, status labels) on every surface.
  ["primary", "bg"],
  ["primary", "surface"],
  ["primary", "surface-raised"],
  ["accent", "bg"],
  ["accent", "surface"],
  ["success", "bg"],
  ["success", "surface"],
  ["warning", "bg"],
  ["warning", "surface"],
  ["danger", "bg"],
  ["danger", "surface"],
  ["danger", "surface-raised"],
  ["info", "bg"],
  ["info", "surface"],
];

/** Pairs rendered as borders, focus rings and controls: WCAG AA needs 3:1. */
export const UI_PAIRS: readonly (readonly [foreground: ColorToken, background: ColorToken])[] = [
  ["line-strong", "bg"],
  ["line-strong", "surface"],
  ["line-strong", "surface-raised"],
  ["focus", "bg"],
  ["focus", "surface"],
  ["focus", "surface-raised"],
  ["primary", "bg"],
];

export const AA_TEXT = 4.5;
export const AA_UI = 3;

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

function channels(hex: string): [number, number, number] {
  if (!HEX.test(hex)) {
    throw new Error(`not a hex colour: ${hex}`);
  }
  const digits = hex.length === 4 ? [...hex.slice(1)].map((d) => d + d).join("") : hex.slice(1);
  const value = Number.parseInt(digits, 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

/** WCAG 2.x relative luminance of a `#rgb` or `#rrggbb` colour. */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = channels(hex).map((channel) => {
    const s = channel / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2.x contrast ratio between two colours, from 1 to 21, independent of order. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const [lighter, darker] = la >= lb ? [la, lb] : [lb, la];
  return (lighter + 0.05) / (darker + 0.05);
}

export interface ContrastResult {
  foreground: ColorToken;
  background: ColorToken;
  ratio: number;
  minimum: number;
  ok: boolean;
}

/** Evaluates every text and UI pair against one scheme's token values. */
export function checkContrast(tokens: Record<string, string>): ContrastResult[] {
  const evaluate = (
    pairs: readonly (readonly [ColorToken, ColorToken])[],
    minimum: number,
  ): ContrastResult[] =>
    pairs.map(([foreground, background]) => {
      const fg = tokens[foreground];
      const bg = tokens[background];
      if (fg === undefined || bg === undefined) {
        throw new Error(`missing token for pair ${foreground}/${background}`);
      }
      const ratio = contrastRatio(fg, bg);
      return { foreground, background, ratio, minimum, ok: ratio >= minimum };
    });
  return [...evaluate(TEXT_PAIRS, AA_TEXT), ...evaluate(UI_PAIRS, AA_UI)];
}
