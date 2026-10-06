import { describe, expect, it } from "vitest";
import { documentTypeOptions, hitCountOptions, parseSearchForm } from "./search-form";

function form(values: Record<string, string | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) {
    for (const one of Array.isArray(value) ? value : [value]) data.append(key, one);
  }
  return data;
}

describe("parseSearchForm", () => {
  it("reads the words with the default count and no filter", () => {
    expect(parseSearchForm(form({ text: " Example words " }))).toEqual({
      ok: true,
      values: { text: "Example words", regulator: "", docTypes: [], asOf: "", k: "" },
      query: { text: "Example words", docTypes: [], k: 8 },
    });
  });

  it("reads a regulator, document types, a date and a count", () => {
    expect(
      parseSearchForm(
        form({
          text: "Example",
          regulator: "Example regulator",
          doc_type: ["circular", "press_release"],
          as_of: "2000-06-30",
          k: "20",
        }),
      ),
    ).toMatchObject({
      ok: true,
      query: {
        text: "Example",
        regulator: "Example regulator",
        docTypes: ["circular", "press_release"],
        asOf: "2000-06-30",
        k: 20,
      },
    });
  });

  it("refuses each malformed field with its message, keeping what was sent", () => {
    const parsed = parseSearchForm(
      form({
        text: "",
        regulator: "x".repeat(41),
        doc_type: ["example"],
        as_of: "2000-99-99",
        k: "7",
      }),
    );
    expect(parsed).toEqual({
      ok: false,
      values: {
        text: "",
        regulator: "x".repeat(41),
        docTypes: ["example"],
        asOf: "2000-99-99",
        k: "7",
      },
      fieldErrors: {
        text: ["Enter the words to search for."],
        regulator: ["A regulator has at most 40 characters."],
        doc_type: ["Choose document types from the list."],
        as_of: ["Enter a date as YYYY-MM-DD."],
        k: ["Choose how many hits from the list."],
      },
    });
    expect(parseSearchForm(form({ text: "x".repeat(2001) }))).toMatchObject({
      ok: false,
      fieldErrors: { text: ["Search with at most 2000 characters."] },
    });
  });

  it("offers the document types and the counts", () => {
    expect(documentTypeOptions().map((option) => option.label)).toEqual([
      "Notification",
      "Circular",
      "Press release",
      "Act amendment",
      "Statute",
    ]);
    expect(hitCountOptions().map((option) => option.value)).toEqual(["8", "20", "50"]);
  });
});
