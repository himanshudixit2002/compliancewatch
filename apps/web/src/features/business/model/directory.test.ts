import { describe, expect, it } from "vitest";
import { ENTITY_ID } from "@/test/business-fixture";
import {
  DIRECTORY_FIELDS,
  SEARCH_MAX_LENGTH,
  directoryPage,
  readDirectoryQuery,
} from "./directory";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

describe("directoryPage", () => {
  it("rows each business with its registrations, the time in IST and its page", () => {
    const page = directoryPage(
      {
        items: [
          {
            id: ENTITY_ID,
            name: "Example business",
            pan: "ABCDE1234F",
            gstins: ["29ABCDE1234F1Z5", "27ABCDE1234F1Z5"],
            updatedAt: "2000-01-04T00:00:00Z",
          },
          {
            id: "b2",
            name: "Example other",
            pan: "ABCDE1234G",
            gstins: [],
            updatedAt: "2000-01-05T00:00:00Z",
          },
        ],
        nextCursor: "example-cursor",
      },
      "example",
      2,
      (id) => `/b/${id}`,
    );
    expect(page).toMatchObject({ q: "example", page: 2, nextCursor: "example-cursor" });
    expect(page.rows[0]).toMatchObject({
      name: "Example business",
      gstins: "29ABCDE1234F1Z5, 27ABCDE1234F1Z5",
      href: `/b/${ENTITY_ID}`,
    });
    expect(page.rows[0]?.updatedAt).toMatch(/IST$/);
    expect(page.rows[1]?.gstins).toBe("None yet");
  });
});

describe("readDirectoryQuery", () => {
  it("reads a trimmed term, the cursor and the page number", () => {
    expect(
      readDirectoryQuery(
        form({
          [DIRECTORY_FIELDS.q]: " acme ",
          [DIRECTORY_FIELDS.cursor]: "c1",
          [DIRECTORY_FIELDS.page]: "3",
        }),
      ),
    ).toEqual({ ok: true, q: "acme", cursor: "c1", page: 3 });
  });

  it("falls back to the first page and no cursor", () => {
    expect(readDirectoryQuery(form({ [DIRECTORY_FIELDS.page]: "zero" }))).toEqual({
      ok: true,
      q: "",
      cursor: undefined,
      page: 1,
    });
  });

  it("refuses a term longer than the service takes", () => {
    const query = readDirectoryQuery(
      form({ [DIRECTORY_FIELDS.q]: "x".repeat(SEARCH_MAX_LENGTH + 1) }),
    );
    expect(query).toEqual({
      ok: false,
      error: `Search with at most ${SEARCH_MAX_LENGTH} characters.`,
    });
  });
});
