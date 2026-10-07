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

  it("reads two equal lists past the table limit as unchanged", () => {
    const side = Array.from({ length: 501 }, (_, n) => `Example line ${n}`);
    expect(side.length * side.length).toBeGreaterThan(MAX_CELLS);
    const lines = diffLines(side, [...side]);
    expect(lines).toHaveLength(501);
    expect(hasChanges(lines)).toBe(false);
  });

  it("keeps a long shared start and end, and marks only the line between that changed", () => {
    const side = Array.from({ length: 600 }, (_, n) => `Example line ${n}`);
    const changed = side.map((line, n) => (n === 300 ? "Example changed line" : line));
    const lines = diffLines(side, changed);
    expect(lines.filter((line) => line.kind !== "same")).toEqual([
      { kind: "removed", text: "Example line 300" },
      { kind: "added", text: "Example changed line" },
    ]);
    expect(lines).toHaveLength(601);
    expect(lines[0]).toEqual({ kind: "same", text: "Example line 0" });
    expect(lines.at(-1)).toEqual({ kind: "same", text: "Example line 599" });
  });

  it("lists the lines between whole past the table limit, keeping the shared start and end", () => {
    const middle = Math.ceil(Math.sqrt(MAX_CELLS)) + 1;
    const left = [
      "Example start",
      ...Array.from({ length: middle }, (_, n) => `a${n}`),
      "Example end",
    ];
    const right = [
      "Example start",
      ...Array.from({ length: middle }, (_, n) => `b${n}`),
      "Example end",
    ];
    const lines = diffLines(left, right);
    expect(lines).toHaveLength(middle * 2 + 2);
    expect(lines[0]).toEqual({ kind: "same", text: "Example start" });
    expect(lines[1]).toEqual({ kind: "removed", text: "a0" });
    expect(lines[middle + 1]).toEqual({ kind: "added", text: "b0" });
    expect(lines.at(-1)).toEqual({ kind: "same", text: "Example end" });
  });
});

describe("hasChanges", () => {
  it("is true only when a line is not shared", () => {
    expect(hasChanges(diffLines(["a"], ["a"]))).toBe(false);
    expect(hasChanges(diffLines(["a"], ["b"]))).toBe(true);
  });
});
