/**
 * A span inside a text, cut into what comes before it, the span and what follows. The rulebook
 * and the pipeline count offsets in Unicode code points (Python string indices), start inclusive
 * and end exclusive, while a JavaScript string counts UTF-16 units; the text is split into code
 * points first, so a character outside the Basic Multilingual Plane still counts as one.
 */
export interface HighlightParts {
  before: string;
  mark: string;
  after: string;
}

/** The parts for [start, end) in code points, or null when the span does not fit the text. */
export function highlightSpan(text: string, start: number, end: number): HighlightParts | null {
  if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  if (start < 0 || end <= start) return null;
  const points = Array.from(text);
  if (end > points.length) return null;
  return {
    before: points.slice(0, start).join(""),
    mark: points.slice(start, end).join(""),
    after: points.slice(end).join(""),
  };
}

/** The length of a text in code points, the unit spans are counted in. */
export function codePointLength(text: string): number {
  return Array.from(text).length;
}
