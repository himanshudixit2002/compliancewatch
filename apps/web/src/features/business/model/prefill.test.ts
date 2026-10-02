import { describe, expect, it } from "vitest";
import { businessCreatedFromDto } from "@/entities/business/mappers";
import type { LookupResult } from "@/entities/business/types";
import { ontologyFromDto } from "@/entities/ontology/mappers";
import { BUSINESS_CREATED_DTO, DEMO_GSTIN, ENTITY_ID, TASK_ID } from "@/test/business-fixture";
import { ONTOLOGY_DTO } from "@/test/ontology-fixture";
import { businessStepResult, lookupRows } from "./prefill";

/** The fixture ontology plus the keys the lookup words, with synthetic labels. */
const ONTOLOGY = ontologyFromDto({
  ...ONTOLOGY_DTO,
  attributes: [
    ...ONTOLOGY_DTO.attributes,
    {
      key: "registration_type",
      type: "enum",
      level: "registration",
      source: "gstin_lookup",
      per_financial_year: false,
      definition: "Example definition.",
      question: "Example question?",
      help: "",
      values: [{ value: "regular", label: "Example regular kind" }],
      min: null,
      max: null,
      example: null,
    },
    {
      key: "registered_since",
      type: "date",
      level: "registration",
      source: "gstin_lookup",
      per_financial_year: false,
      definition: "Example definition.",
      question: "Example question?",
      help: "",
      values: [],
      min: null,
      max: null,
      example: null,
    },
  ],
});

const RESULT: LookupResult = {
  gstin: DEMO_GSTIN,
  legalName: "Example Legal Name Limited",
  tradeName: "Example trade name",
  registrationType: "regular",
  gstinStatus: "active",
  stateCode: "01",
  constitution: "",
  registeredSince: "2000-07-01",
  businessCategory: "",
  natureOfBusiness: ["example_activity", "another_activity"],
};

const HREFS = { questions: "/onboarding/b/questions", done: "/onboarding/b/done" };

describe("lookupRows", () => {
  it("words each looked-up value with the ontology and leaves out the empty ones", () => {
    expect(lookupRows(RESULT, ONTOLOGY)).toEqual([
      { key: "legalName", label: "Legal name", value: "Example Legal Name Limited" },
      { key: "tradeName", label: "Trade name", value: "Example trade name" },
      { key: "registrationType", label: "Registration type", value: "Example regular kind" },
      { key: "gstinStatus", label: "GSTIN status", value: "Active" },
      { key: "stateCode", label: "State", value: "01 (Example place one)" },
      { key: "registeredSince", label: "Registered since", value: "1 Jul 2000" },
      {
        key: "natureOfBusiness",
        label: "Nature of business",
        value: "example_activity, another_activity",
      },
    ]);
  });

  it("falls back to the raw values without an ontology", () => {
    const rows = lookupRows({ ...RESULT, stateCode: "02", constitution: "example_kind" }, null);
    expect(rows.find((row) => row.key === "stateCode")?.value).toBe("02");
    expect(rows.find((row) => row.key === "constitution")?.value).toBe("Example kind");
    expect(rows.find((row) => row.key === "registeredSince")?.value).toBe("1 Jul 2000");
    expect(rows.find((row) => row.key === "registrationType")?.value).toBe("Regular");
  });

  it("keeps a state code the ontology does not list as it is", () => {
    const rows = lookupRows({ ...RESULT, stateCode: "97" }, ONTOLOGY);
    expect(rows.find((row) => row.key === "stateCode")?.value).toBe("97");
  });
});

describe("businessStepResult", () => {
  it("summarises a new business whose GSTIN the lookup did not know", () => {
    const created = businessCreatedFromDto(BUSINESS_CREATED_DTO);
    expect(businessStepResult(created, DEMO_GSTIN, ONTOLOGY, HREFS)).toEqual({
      businessId: ENTITY_ID,
      businessName: "Example business",
      pan: "ABCDE1234F",
      gstin: DEMO_GSTIN,
      created: true,
      lookedUp: false,
      rows: [],
      applied: [],
      reviewTaskId: TASK_ID,
      progressText: "4 of 8 answered",
      complete: false,
      nextHref: HREFS.questions,
    });
  });

  it("lists what the lookup stored, and points at the summary when nothing is left", () => {
    const created = businessCreatedFromDto({
      ...BUSINESS_CREATED_DTO,
      created: false,
      prefill: {
        node_id: ENTITY_ID,
        looked_up: true,
        result: {
          gstin: DEMO_GSTIN,
          legal_name: "Example Legal Name Limited",
          trade_name: "Example trade name",
          registration_type: "regular",
          gstin_status: "active",
          state_code: "01",
          constitution: "example_kind",
          registered_since: null,
        },
        applied: ["registration_type", "state_codes"],
        review_task: null,
      },
      onboarding: { ...BUSINESS_CREATED_DTO.onboarding, answered: 8, complete: true, next: null },
    });
    const result = businessStepResult(created, DEMO_GSTIN, ONTOLOGY, HREFS);
    expect(result.created).toBe(false);
    expect(result.lookedUp).toBe(true);
    expect(result.applied).toEqual(["Registration type", "State codes"]);
    expect(result.rows.map((row) => row.key)).toContain("constitution");
    expect(result.reviewTaskId).toBeNull();
    expect(result.nextHref).toBe(HREFS.done);
  });

  it("reads a business made from its PAN alone as not looked up", () => {
    const created = businessCreatedFromDto({ ...BUSINESS_CREATED_DTO, prefill: null });
    const result = businessStepResult(created, DEMO_GSTIN, null, HREFS);
    expect(result.lookedUp).toBe(false);
    expect(result.reviewTaskId).toBeNull();
    expect(result.applied).toEqual([]);
  });
});
