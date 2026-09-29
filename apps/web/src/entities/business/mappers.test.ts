import { describe, expect, it } from "vitest";
import {
  BUSINESS_CREATED_DTO,
  BUSINESS_DTO,
  DEMO_GSTIN,
  ENTITY_ID,
  LOCATION_DTO,
  ONBOARDING_DTO,
  REGISTRATION_DTO,
  REGISTRATION_ID,
  REVIEW_TASK_DTO,
  SNAPSHOT_DTO,
  TASK_ID,
} from "@/test/business-fixture";
import {
  answerToDto,
  businessChangesToDto,
  businessCreatedFromDto,
  businessFromDto,
  businessPageFromDto,
  isValueState,
  newBusinessToDto,
  newLocationToDto,
  newRegistrationToDto,
  onboardingFromDto,
  prefillFromDto,
  profileNodeFromDto,
  registrationAddedFromDto,
  reviewTaskFromDto,
  snapshotFromDto,
  valueOf,
} from "./mappers";

describe("from the wire", () => {
  it("maps a business with its entity values and registrations", () => {
    const business = businessFromDto(BUSINESS_DTO);
    expect(business).toMatchObject({
      id: ENTITY_ID,
      name: "Example business",
      pan: "ABCDE1234F",
      version: 5,
      createdAt: "2000-01-01T00:00:00Z",
      updatedAt: "2000-01-04T00:00:00Z",
    });
    expect(business.attributes[1]).toEqual({
      key: "example_band",
      state: "known",
      value: "medium",
      asOfFy: "2000-01",
      source: "user_input",
      updatedAt: "2000-01-03T00:00:00Z",
    });
    // An unsure value has no value and may have no time.
    expect(business.attributes[2]).toMatchObject({ state: "unsure", value: null, updatedAt: null });
    expect(business.registrations[0]).toMatchObject({
      id: REGISTRATION_ID,
      level: "registration",
      key: DEMO_GSTIN,
      parentId: ENTITY_ID,
      created: false,
    });
  });

  it("maps a node without a parent or a created flag", () => {
    const bare = { ...LOCATION_DTO, parent_id: null };
    delete bare.created;
    expect(profileNodeFromDto(bare)).toMatchObject({
      parentId: null,
      created: false,
      attributes: [],
    });
    expect(profileNodeFromDto(LOCATION_DTO).created).toBe(true);
  });

  it("maps a page of summaries with its cursor", () => {
    const page = businessPageFromDto({
      items: [
        {
          id: ENTITY_ID,
          name: "Example business",
          pan: "ABCDE1234F",
          gstins: [DEMO_GSTIN],
          updated_at: "2000-01-04T00:00:00Z",
        },
      ],
      next_cursor: "example-cursor",
    });
    expect(page).toEqual({
      items: [
        {
          id: ENTITY_ID,
          name: "Example business",
          pan: "ABCDE1234F",
          gstins: [DEMO_GSTIN],
          updatedAt: "2000-01-04T00:00:00Z",
        },
      ],
      nextCursor: "example-cursor",
    });
    expect(businessPageFromDto({ items: [], next_cursor: null }).nextCursor).toBeNull();
  });

  it("maps onboarding with the next question, and a finished one without", () => {
    const onboarding = onboardingFromDto(ONBOARDING_DTO);
    expect(onboarding).toMatchObject({
      businessId: ENTITY_ID,
      asOfFy: "2000-01",
      answered: 4,
      total: 8,
      complete: false,
    });
    expect(onboarding.next).toEqual({
      nodeId: REGISTRATION_ID,
      level: "registration",
      key: "example_flag",
      state: "missing",
      perFinancialYear: false,
      asOfFy: null,
      type: "boolean",
      question: "Example question about example_flag?",
      help: "",
      options: [],
      min: null,
      max: null,
    });
    const done = onboardingFromDto({ ...ONBOARDING_DTO, complete: true, answered: 8, next: null });
    expect(done.next).toBeNull();
  });

  it("maps a creation with its prefill, and a prefill that looked something up", () => {
    const created = businessCreatedFromDto(BUSINESS_CREATED_DTO);
    expect(created.created).toBe(true);
    expect(created.prefill).toEqual({
      nodeId: REGISTRATION_ID,
      lookedUp: false,
      result: null,
      applied: [],
      reviewTaskId: TASK_ID,
    });
    expect(businessCreatedFromDto({ ...BUSINESS_CREATED_DTO, prefill: null }).prefill).toBeNull();
    const looked = prefillFromDto({
      node_id: REGISTRATION_ID,
      looked_up: true,
      applied: ["example_kind"],
      review_task: null,
      result: {
        gstin: DEMO_GSTIN,
        legal_name: "Example legal name",
        trade_name: "Example trade name",
        registration_type: "first",
        gstin_status: "active",
        state_code: "29",
        constitution: "other",
        registered_since: "2000-01-01",
        nature_of_business: ["Example activity"],
      },
    });
    expect(looked.result).toEqual({
      gstin: DEMO_GSTIN,
      legalName: "Example legal name",
      tradeName: "Example trade name",
      registrationType: "first",
      gstinStatus: "active",
      stateCode: "29",
      constitution: "other",
      registeredSince: "2000-01-01",
      businessCategory: "",
      natureOfBusiness: ["Example activity"],
    });
    expect(looked.reviewTaskId).toBeNull();
  });

  it("maps an added registration", () => {
    const added = registrationAddedFromDto({
      business: BUSINESS_DTO,
      registration: REGISTRATION_DTO,
      created: false,
      prefill: BUSINESS_CREATED_DTO.prefill as NonNullable<typeof BUSINESS_CREATED_DTO.prefill>,
    });
    expect(added.created).toBe(false);
    expect(added.registration.id).toBe(REGISTRATION_ID);
    expect(added.business.id).toBe(ENTITY_ID);
  });

  it("maps review tasks and snapshots", () => {
    expect(reviewTaskFromDto(REVIEW_TASK_DTO)).toEqual({
      id: TASK_ID,
      nodeId: REGISTRATION_ID,
      attributeKey: "example_flag",
      reason: "not_applicable",
      asOfFy: null,
      open: true,
      createdAt: "2000-01-03T00:00:00Z",
    });
    expect(snapshotFromDto(SNAPSHOT_DTO)).toMatchObject({
      version: 8,
      level: "registration",
      lineage: [ENTITY_ID, REGISTRATION_ID],
      asOfFy: "2000-01",
      attributes: { example_band: "medium" },
    });
  });
});

describe("to the wire", () => {
  it("sends a value only with a known state, and the year and node only when set", () => {
    expect(
      answerToDto({ key: "example_band", state: "known", value: "small", asOfFy: "2000-01" }),
    ).toEqual({ key: "example_band", state: "known", value: "small", as_of_fy: "2000-01" });
    expect(
      answerToDto({ key: "example_flag", state: "unsure", value: true, nodeId: REGISTRATION_ID }),
    ).toEqual({ key: "example_flag", state: "unsure", node_id: REGISTRATION_ID });
    expect(answerToDto({ key: "example_flag", state: "not_applicable", asOfFy: null })).toEqual({
      key: "example_flag",
      state: "not_applicable",
    });
  });

  it("builds a new business from a GSTIN or a PAN, without node ids on its answers", () => {
    expect(newBusinessToDto({ name: "Example", gstin: DEMO_GSTIN })).toEqual({
      name: "Example",
      gstin: DEMO_GSTIN,
    });
    expect(
      newBusinessToDto({
        name: "Example",
        pan: "ABCDE1234F",
        gstin: "",
        registrationName: "Example registration",
        answers: [{ key: "example_count", state: "known", value: 3, nodeId: REGISTRATION_ID }],
      }),
    ).toEqual({
      name: "Example",
      pan: "ABCDE1234F",
      registration_name: "Example registration",
      answers: [{ key: "example_count", state: "known", value: 3 }],
    });
    expect(newBusinessToDto({ name: "Example", answers: [] })).toEqual({ name: "Example" });
  });

  it("builds a patch, a registration and a location", () => {
    expect(businessChangesToDto({})).toEqual({});
    expect(
      businessChangesToDto({
        name: "Renamed",
        changes: [{ key: "example_kind", state: "known", value: "first" }],
      }),
    ).toEqual({
      name: "Renamed",
      changes: [{ key: "example_kind", state: "known", value: "first" }],
    });
    expect(newRegistrationToDto({ gstin: DEMO_GSTIN })).toEqual({ gstin: DEMO_GSTIN });
    expect(newRegistrationToDto({ gstin: DEMO_GSTIN, name: "Example" })).toEqual({
      gstin: DEMO_GSTIN,
      name: "Example",
    });
    expect(
      newLocationToDto({ registrationId: REGISTRATION_ID, label: "EX-01", name: "Example" }),
    ).toEqual({ registration_id: REGISTRATION_ID, label: "EX-01", name: "Example" });
  });
});

describe("lookups", () => {
  it("recognises the value states", () => {
    expect(isValueState("not_applicable")).toBe(true);
    expect(isValueState("missing")).toBe(false);
  });

  it("finds a node's value for a key, per year when the value is stated per year", () => {
    const values = businessFromDto(BUSINESS_DTO).attributes;
    expect(valueOf(values, "example_band", "2000-01")?.value).toBe("medium");
    expect(valueOf(values, "example_band", "2001-02")).toBeUndefined();
    expect(valueOf(values, "state_codes", "2000-01")?.value).toEqual(["01", "02"]);
    expect(valueOf(values, "state_codes")?.value).toEqual(["01", "02"]);
    expect(valueOf(values, "missing")).toBeUndefined();
  });
});
