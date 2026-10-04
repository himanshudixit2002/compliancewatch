import { describe, expect, it } from "vitest";
import { codePointLength, highlightSpan, markSpans } from "./highlight";

describe("highlightSpan", () => {
  it("cuts the text around the span, end exclusive", () => {
    expect(highlightSpan("Example clause text", 8, 14)).toEqual({
      before: "Example ",
      mark: "clause",
      after: " text",
    });
    expect(highlightSpan("abc", 0, 3)).toEqual({ before: "", mark: "abc", after: "" });
  });

  it("counts code points, as the services do, not UTF-16 units", () => {
    const text = "a\u{1F600}b – c";
    expect(text.length).toBe(8);
    expect(codePointLength(text)).toBe(7);
    expect(highlightSpan(text, 1, 3)).toEqual({ before: "a", mark: "\u{1F600}b", after: " – c" });
    expect(highlightSpan(text, 4, 5)?.mark).toBe("–");
  });

  it("refuses a span that does not fit the text", () => {
    expect(highlightSpan("abc", 2, 4)).toBeNull();
    expect(highlightSpan("abc", -1, 2)).toBeNull();
    expect(highlightSpan("abc", 2, 2)).toBeNull();
    expect(highlightSpan("abc", 2, 1)).toBeNull();
    expect(highlightSpan("abc", 0.5, 2)).toBeNull();
    expect(highlightSpan("abc", 0, Number.NaN)).toBeNull();
  });
});

describe("markSpans", () => {
  it("cuts the text into plain and marked runs, in code points", () => {
    expect(
      markSpans("Example 𝔸 text here", [
        { start: 8, end: 9 },
        { start: 15, end: 19 },
      ]),
    ).toEqual([
      { text: "Example ", mark: false },
      { text: "𝔸", mark: true },
      { text: " text ", mark: false },
      { text: "here", mark: true },
    ]);
  });

  it("merges overlapping spans, sorts them and leaves out those that do not fit", () => {
    expect(
      markSpans("Example text", [
        { start: 8, end: 12 },
        { start: 0, end: 3 },
        { start: 2, end: 7 },
        { start: 5, end: 99 },
        { start: 4, end: 4 },
        { start: 1.5, end: 2 },
      ]),
    ).toEqual([
      { text: "Example", mark: true },
      { text: " ", mark: false },
      { text: "text", mark: true },
    ]);
  });

  it("keeps a text without spans as one plain run, the empty text included", () => {
    expect(markSpans("Example", [])).toEqual([{ text: "Example", mark: false }]);
    expect(markSpans("", [])).toEqual([{ text: "", mark: false }]);
  });
});
