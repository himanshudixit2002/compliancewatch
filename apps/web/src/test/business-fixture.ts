import type {
  BusinessCreatedDto,
  BusinessDto,
  OnboardingDto,
  PrefillDto,
  ProfileNodeDto,
  ReviewTaskDto,
  SnapshotDto,
} from "@/entities/business/types";

/**
 * Profile service bodies for unit tests, with fixed synthetic ids, the repository's demo GSTIN
 * and the attribute keys of src/test/ontology-fixture.ts. The e2e suite reads real ones.
 */
export const TENANT_ID = "2a6f0c1e-5b7d-4e8f-9a0b-1c2d3e4f5a6b";
export const USER_ID = "7c1e2d3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";
export const ENTITY_ID = "00000000-0000-4000-8000-0000000000e1";
export const REGISTRATION_ID = "00000000-0000-4000-8000-0000000000a1";
export const LOCATION_ID = "00000000-0000-4000-8000-0000000000c1";
export const TASK_ID = "00000000-0000-4000-8000-0000000000f1";
export const DEMO_GSTIN = "29ABCDE1234F1Z5";
export const DEMO_PAN = "ABCDE1234F";

export const REGISTRATION_DTO: ProfileNodeDto = {
  id: REGISTRATION_ID,
  level: "registration",
  key: DEMO_GSTIN,
  name: "Example registration",
  parent_id: ENTITY_ID,
  version: 3,
  created: false,
  attributes: [
    {
      key: "example_kind",
      state: "known",
      value: "second",
      as_of_fy: null,
      source: "gstin_lookup",
      updated_at: "2000-01-02T03:04:05Z",
    },
    {
      key: "example_flag",
      state: "not_applicable",
      as_of_fy: null,
      source: "user_input",
      updated_at: "2000-01-03T00:00:00Z",
    },
  ],
};

export const LOCATION_DTO: ProfileNodeDto = {
  id: LOCATION_ID,
  level: "location",
  key: "EX-01",
  name: "Example location",
  parent_id: REGISTRATION_ID,
  version: 1,
  created: true,
  attributes: [],
};

export const BUSINESS_DTO: BusinessDto = {
  id: ENTITY_ID,
  name: "Example business",
  pan: DEMO_PAN,
  version: 5,
  created_at: "2000-01-01T00:00:00Z",
  updated_at: "2000-01-04T00:00:00Z",
  attributes: [
    {
      key: "state_codes",
      state: "known",
      value: ["01", "02"],
      as_of_fy: null,
      source: "gstin_lookup",
      updated_at: "2000-01-02T03:04:05Z",
    },
    {
      key: "example_band",
      state: "known",
      value: "medium",
      as_of_fy: "2000-01",
      source: "user_input",
      updated_at: "2000-01-03T00:00:00Z",
    },
    {
      key: "example_count",
      state: "unsure",
      as_of_fy: null,
      source: "user_input",
      updated_at: null,
    },
  ],
  registrations: [REGISTRATION_DTO],
};

export const ONBOARDING_DTO: OnboardingDto = {
  business_id: ENTITY_ID,
  as_of_fy: "2000-01",
  answered: 4,
  total: 8,
  complete: false,
  next: {
    node_id: REGISTRATION_ID,
    level: "registration",
    key: "example_flag",
    state: "missing",
    per_financial_year: false,
    as_of_fy: null,
    type: "boolean",
    question: "Example question about example_flag?",
    help: "",
    options: [],
    min: null,
    max: null,
  },
};

export const PREFILL_DTO: PrefillDto = {
  node_id: REGISTRATION_ID,
  looked_up: false,
  result: null,
  applied: [],
  review_task: TASK_ID,
};

export const BUSINESS_CREATED_DTO: BusinessCreatedDto = {
  business: BUSINESS_DTO,
  created: true,
  prefill: PREFILL_DTO,
  onboarding: ONBOARDING_DTO,
};

export const REVIEW_TASK_DTO: ReviewTaskDto = {
  id: TASK_ID,
  node_id: REGISTRATION_ID,
  attribute_key: "example_flag",
  reason: "not_applicable",
  as_of_fy: null,
  open: true,
  created_at: "2000-01-03T00:00:00Z",
};

export const SNAPSHOT_DTO: SnapshotDto = {
  business_id: REGISTRATION_ID,
  tenant_id: TENANT_ID,
  version: 8,
  level: "registration",
  // The service lists the ancestors only; the node itself is business_id.
  lineage: [ENTITY_ID],
  as_of_fy: "2000-01",
  attributes: {
    state_codes: ["01", "02"],
    example_band: "medium",
    example_kind: "second",
  },
};
