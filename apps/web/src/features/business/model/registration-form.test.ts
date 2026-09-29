import { describe, expect, it } from "vitest";
import { registrationAddedFromDto } from "@/entities/business/mappers";
import {
  BUSINESS_DTO,
  DEMO_PAN,
  ENTITY_ID,
  PREFILL_DTO,
  REGISTRATION_DTO,
} from "@/test/business-fixture";
import {
  REGISTRATION_FIELDS,
  panMismatch,
  parseRegistrationForm,
  registrationAddedResult,
} from "./registration-form";

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

describe("parseRegistrationForm", () => {
  it("normalises the GSTIN and keeps a name only when one is given", () => {
    expect(
      parseRegistrationForm(
        form({ business_id: ENTITY_ID, gstin: " 27abcde 1234f1z5 ", name: "" }),
      ),
    ).toEqual({ ok: true, value: { businessId: ENTITY_ID, gstin: "27ABCDE1234F1Z5" } });
    expect(
      parseRegistrationForm(
        form({ business_id: ENTITY_ID, gstin: "27ABCDE1234F1Z5", name: " Example branch " }),
      ),
    ).toEqual({
      ok: true,
      value: { businessId: ENTITY_ID, gstin: "27ABCDE1234F1Z5", name: "Example branch" },
    });
  });

  it("names the fields to fix, and refuses a tampered business id outright", () => {
    expect(parseRegistrationForm(form({ business_id: ENTITY_ID, gstin: "" }))).toEqual({
      ok: false,
      fieldErrors: { gstin: ["Enter the GSTIN."] },
    });
    const bad = parseRegistrationForm(
      form({ business_id: ENTITY_ID, gstin: "27ABC", name: "x".repeat(201) }),
    );
    expect(bad.ok === false && Object.keys(bad.fieldErrors ?? {})).toEqual(["gstin", "name"]);
    expect(
      parseRegistrationForm(form({ business_id: "not-a-uuid", gstin: "27ABCDE1234F1Z5" })),
    ).toEqual({ ok: false, formError: expect.any(String) });
    expect(REGISTRATION_FIELDS).toEqual({
      businessId: "business_id",
      gstin: "gstin",
      name: "name",
    });
  });
});

describe("panMismatch", () => {
  it("accepts a GSTIN of the business's PAN and explains one of another PAN", () => {
    expect(panMismatch("27ABCDE1234F1Z5", DEMO_PAN)).toBeNull();
    expect(panMismatch("27ZZZZZ9999Z1Z5", DEMO_PAN)).toEqual({
      gstin: [
        "This GSTIN carries the PAN ZZZZZ9999Z, not this business's PAN ABCDE1234F; it belongs to another business, which the business step adds.",
      ],
    });
  });
});

describe("registrationAddedResult", () => {
  it("names the registration, the lookup's outcome and the links to its pages", () => {
    const added = registrationAddedFromDto({
      business: BUSINESS_DTO,
      registration: { ...REGISTRATION_DTO, created: true },
      created: true,
      prefill: {
        ...PREFILL_DTO,
        looked_up: true,
        applied: ["registration_type"],
        review_task: null,
      },
    });
    expect(
      registrationAddedResult(added, {
        attributes: "/b/x/attributes",
        reviewTasks: "/b/x/review-tasks",
      }),
    ).toEqual({
      registrationId: REGISTRATION_DTO.id,
      gstin: REGISTRATION_DTO.key,
      name: REGISTRATION_DTO.name,
      created: true,
      lookedUp: true,
      applied: ["Registration type"],
      attributesHref: `/b/x/attributes?node=${REGISTRATION_DTO.id}`,
      reviewTasksHref: "/b/x/review-tasks",
    });
  });
});
