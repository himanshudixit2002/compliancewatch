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

/** A run of text, marked or not, in the order it reads. */
export interface TextSegment {
  text: string;
  mark: boolean;
}

/**
 * The text cut into plain and marked runs at [start, end) ranges counted in code points, such
 * as the spans of an entity's mentions in a clause. The ranges are sorted, overlapping ones are
 * merged, and a range that does not fit the text is left out, so the runs always join back into
 * the text.
 */
export function markSpans(
  text: string,
  spans: readonly { start: number; end: number }[],
): TextSegment[] {
  const points = Array.from(text);
  const valid = spans
    .filter(
      (span) =>
        Number.isInteger(span.start) &&
        Number.isInteger(span.end) &&
        span.start >= 0 &&
        span.end > span.start &&
        span.end <= points.length,
    )
    .map((span) => ({ start: span.start, end: span.end }))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  const merged: { start: number; end: number }[] = [];
  for (const span of valid) {
    const last = merged.at(-1);
    if (last !== undefined && span.start <= last.end) last.end = Math.max(last.end, span.end);
    else merged.push(span);
  }
  const segments: TextSegment[] = [];
  let cursor = 0;
  for (const span of merged) {
    if (span.start > cursor) {
      segments.push({ text: points.slice(cursor, span.start).join(""), mark: false });
    }
    segments.push({ text: points.slice(span.start, span.end).join(""), mark: true });
    cursor = span.end;
  }
  if (cursor < points.length || segments.length === 0) {
    segments.push({ text: points.slice(cursor).join(""), mark: false });
  }
  return segments;
}

/**
 * Where a quote stands in a text, word for word, as a [start, end) range in code points (the
 * unit `markSpans` and the services count in); null when the text does not hold it exactly. A
 * verified quote may still be missing: the rulebook verifies a quote by a match score, so a
 * quote with different spacing or punctuation passes there and is not found here.
 */
export function quoteSpan(text: string, quote: string): { start: number; end: number } | null {
  if (quote === "") return null;
  const at = text.indexOf(quote);
  if (at < 0) return null;
  const start = codePointLength(text.slice(0, at));
  return { start, end: start + codePointLength(quote) };
}
