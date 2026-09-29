import { describe, expect, it } from "vitest";
import { codePointLength, highlightSpan } from "./highlight";

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
