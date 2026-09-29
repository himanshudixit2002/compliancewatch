import { describe, expect, it } from "vitest";
import { BUSINESS_FORM_FIELDS, NAME_MAX_LENGTH, parseBusinessForm } from "./business-form";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

describe("parseBusinessForm", () => {
  it("normalises the GSTIN and keeps the names as typed, trimmed", () => {
    const parsed = parseBusinessForm(
      form({ gstin: " 29abcde 1234f1z5 ", name: " Example business ", registration_name: "" }),
    );
    expect(parsed).toEqual({
      ok: true,
      value: { gstin: "29ABCDE1234F1Z5", name: "Example business" },
    });
  });

  it("carries a registration name when one is given", () => {
    const parsed = parseBusinessForm(
      form({ gstin: "29ABCDE1234F1Z5", name: "Example", registration_name: "Example branch" }),
    );
    expect(parsed.ok && parsed.value.registrationName).toBe("Example branch");
  });

  it("names each field that fails, under the API's field names", () => {
    expect(parseBusinessForm(form({}))).toEqual({
      ok: false,
      fieldErrors: {
        [BUSINESS_FORM_FIELDS.gstin]: ["Enter the GSTIN."],
        [BUSINESS_FORM_FIELDS.name]: ["Enter the name the business goes by."],
      },
    });
    const long = "x".repeat(NAME_MAX_LENGTH + 1);
    const parsed = parseBusinessForm(
      form({ gstin: "29ABCDE1234", name: long, registration_name: long }),
    );
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.fieldErrors.gstin?.[0]).toMatch(/^Enter the GSTIN as 15 characters/);
    expect(parsed.fieldErrors.name).toEqual([`Use at most ${NAME_MAX_LENGTH} characters.`]);
    expect(parsed.fieldErrors.registration_name).toEqual([
      `Use at most ${NAME_MAX_LENGTH} characters.`,
    ]);
  });

  it("ignores a field submitted as a file", () => {
    const data = form({ name: "Example" });
    data.append("gstin", new Blob(["29ABCDE1234F1Z5"]));
    expect(parseBusinessForm(data).ok).toBe(false);
  });
});
