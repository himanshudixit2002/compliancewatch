import { describe, expect, it } from "vitest";
import { blockCounts, clausesOf, readTranscript } from "./transcript";

describe("readTranscript", () => {
  it("reads headings, numbered paragraphs, tables with a header, and pages", () => {
    const read = readTranscript(
      [
        "# Example heading",
        "",
        "1. Example text of the first",
        "paragraph, on two lines.",
        "",
        "(a) Example clause (a).",
        "",
        "[page 2]",
        "| S. No. | Item |",
        "|---|---|",
        "| 1 | Example item |",
        "| 2 | |",
        "",
        "An unnumbered example paragraph.",
        "",
        "| Example | without header |",
      ].join("\r\n"),
    );
    expect(read.ok).toBe(true);
    expect(read.blocks).toEqual([
      { type: "heading", text: "Example heading", page: null },
      {
        type: "paragraph",
        number: "1.",
        text: "Example text of the first paragraph, on two lines.",
        page: null,
      },
      { type: "paragraph", number: "(a)", text: "Example clause (a).", page: null },
      {
        type: "table",
        header: ["S. No.", "Item"],
        rows: [
          ["1", "Example item"],
          ["2", ""],
        ],
        page: 2,
      },
      { type: "paragraph", number: "", text: "An unnumbered example paragraph.", page: 2 },
      { type: "table", header: null, rows: [["Example", "without header"]], page: 2 },
    ]);
    expect(blockCounts(read.blocks)).toEqual({ headings: 1, paragraphs: 3, tables: 2, clauses: 7 });
    expect(clausesOf(read.blocks[3]!)).toBe(2);
  });

  it("does not read a word with a full stop as a number", () => {
    const read = readTranscript(
      "The. Example sentence.\n\n2A. Example.\n\na) Example.\n\n(iv) Example.",
    );
    expect(read.blocks.map((block) => (block.type === "paragraph" ? block.number : null))).toEqual([
      "",
      "2A.",
      "a)",
      "(iv)",
    ]);
  });

  it("names each problem by its block", () => {
    const read = readTranscript(
      ["#", "", "(1)", "", "| a | b |", "|---|---|", "", "| | |"].join("\n"),
    );
    expect(read.ok).toBe(false);
    if (read.ok) return;
    expect(read.errors).toEqual([
      "Block 1: the heading has no text.",
      "Block 2: the paragraph has no text after its number.",
      "Block 3: the table has a header but no row.",
      "Block 4: row 1 of the table has no text in any cell.",
    ]);
    expect(readTranscript("   \n\n").ok).toBe(false);
  });

  it("holds the pipeline's limits", () => {
    const long = readTranscript(`# ${"x".repeat(50_001)}\n\n${"y".repeat(50_001)}`);
    expect(!long.ok && long.errors).toEqual([
      "Block 1 is longer than 50000 characters.",
      "Block 2 is longer than 50000 characters.",
    ]);
    const wide = readTranscript(`| ${Array.from({ length: 51 }, () => "c").join(" | ")} |`);
    expect(!wide.ok && wide.errors[0]).toBe("Block 1: row 1 has more than 50 cells.");
    const wideHeader = readTranscript(
      `| ${Array.from({ length: 51 }, () => "h").join(" | ")} |\n|---|\n| c |`,
    );
    expect(!wideHeader.ok && wideHeader.errors[0]).toBe("Block 1: row 0 has more than 50 cells.");
    const rows = readTranscript(
      Array.from({ length: 2001 }, (_, index) => `| ${index} |`).join("\n"),
    );
    expect(!rows.ok && rows.errors).toEqual([
      "Block 1: the table has more than 2000 rows.",
      "The transcript makes 2001 clauses; the rulebook takes at most 2000.",
    ]);
  });
});
