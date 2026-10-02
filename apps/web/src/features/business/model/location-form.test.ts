import { describe, expect, it } from "vitest";
import { ENTITY_ID, REGISTRATION_ID } from "@/test/business-fixture";
import { LABEL_MAX_LENGTH, LOCATION_FIELDS, parseLocationForm } from "./location-form";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const IDS = {
  [LOCATION_FIELDS.businessId]: ENTITY_ID,
  [LOCATION_FIELDS.registrationId]: REGISTRATION_ID,
};

describe("parseLocationForm", () => {
  it("reads the label and the name under the business and the registration", () => {
    expect(parseLocationForm(form({ ...IDS, label: " EX-01 ", name: " Example branch " }))).toEqual(
      {
        ok: true,
        value: {
          businessId: ENTITY_ID,
          registrationId: REGISTRATION_ID,
          label: "EX-01",
          name: "Example branch",
        },
      },
    );
  });

  it("names the empty or too long fields", () => {
    expect(parseLocationForm(form(IDS))).toEqual({
      ok: false,
      fieldErrors: { label: ["Enter a label."], name: ["Enter a name."] },
    });
    const long = parseLocationForm(
      form({ ...IDS, label: "x".repeat(LABEL_MAX_LENGTH + 1), name: "y".repeat(201) }),
    );
    expect(long).toEqual({
      ok: false,
      fieldErrors: {
        label: [`Use at most ${LABEL_MAX_LENGTH} characters.`],
        name: ["Use at most 200 characters."],
      },
    });
  });

  it("refuses a tampered hidden field", () => {
    const parsed = parseLocationForm(form({ ...IDS, registration_id: "x", label: "a", name: "b" }));
    expect(parsed.ok).toBe(false);
    expect(!parsed.ok && parsed.formError).toMatch(/Reload the page/);
  });
});
