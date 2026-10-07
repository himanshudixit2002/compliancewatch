import { describe, expect, it } from "vitest";
import { MAX_CELLS, diffLines, hasChanges } from "./diff";

describe("diffLines", () => {
  it("keeps the shared lines and marks what each side alone has, a removal first", () => {
    expect(
      diffLines(
        ["Example first", "Example second", "Example third"],
        ["Example first", "Example changed", "Example third", "Example fourth"],
      ),
    ).toEqual([
      { kind: "same", text: "Example first" },
      { kind: "removed", text: "Example second" },
      { kind: "added", text: "Example changed" },
      { kind: "same", text: "Example third" },
      { kind: "added", text: "Example fourth" },
    ]);
  });

  it("reads an empty side as every line added or removed", () => {
    expect(diffLines([], ["Example"])).toEqual([{ kind: "added", text: "Example" }]);
    expect(diffLines(["Example"], [])).toEqual([{ kind: "removed", text: "Example" }]);
    expect(diffLines([], [])).toEqual([]);
  });

  it("finds a moved line as one removal and one addition around the lines kept", () => {
    const lines = diffLines(["a", "b", "c"], ["b", "c", "a"]);
    expect(lines.filter((line) => line.kind === "same").map((line) => line.text)).toEqual([
      "b",
      "c",
    ]);
    expect(lines).toContainEqual({ kind: "removed", text: "a" });
    expect(lines).toContainEqual({ kind: "added", text: "a" });
  });

  it("stops aligning past the table limit and lists both sides whole", () => {
    const side = Array.from({ length: Math.ceil(Math.sqrt(MAX_CELLS)) + 1 }, (_, n) => `${n}`);
    const lines = diffLines(side, side);
    expect(lines).toHaveLength(side.length * 2);
    expect(lines[0]).toEqual({ kind: "removed", text: "0" });
    expect(lines.at(-1)).toEqual({ kind: "added", text: side.at(-1) });
  });
});

describe("hasChanges", () => {
  it("is true only when a line is not shared", () => {
    expect(hasChanges(diffLines(["a"], ["a"]))).toBe(false);
    expect(hasChanges(diffLines(["a"], ["b"]))).toBe(true);
  });
});
