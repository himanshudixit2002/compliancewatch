import { describe, expect, it } from "vitest";
import { OPEN_FIELDS, parseOpenForm } from "./open-form";

function form(value: string | null): FormData {
  const data = new FormData();
  if (value !== null) data.append(OPEN_FIELDS.documentId, value);
  return data;
}

describe("parseOpenForm", () => {
  it("takes a document id or a sha256", () => {
    expect(parseOpenForm(form(" 51F5DBEE1615F0EC47256ABDDB11061A "))).toEqual({
      ok: true,
      documentId: "51f5dbee-1615-f0ec-4725-6abddb11061a",
    });
  });

  it("names the field when it is empty or malformed", () => {
    expect(parseOpenForm(form(null))).toEqual({
      ok: false,
      fieldErrors: { document_id: ["Enter a document id or a sha256."] },
    });
    expect(parseOpenForm(form("abc"))).toEqual({
      ok: false,
      fieldErrors: {
        document_id: [
          "This is not a document id (32 hex characters) or a sha256 (64 hex characters).",
        ],
      },
    });
  });
});
