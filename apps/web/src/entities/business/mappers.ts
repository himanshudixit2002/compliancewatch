import {
  VALUE_STATES,
  type Answer,
  type AttributeValue,
  type AttributeValueDto,
  type Business,
  type BusinessChangeInDto,
  type BusinessChanges,
  type BusinessCreated,
  type BusinessCreatedDto,
  type BusinessDto,
  type BusinessInDto,
  type BusinessPage,
  type BusinessPageDto,
  type BusinessPatchInDto,
  type BusinessSummary,
  type BusinessSummaryDto,
  type LocationInDto,
  type LookupResult,
  type LookupResultDto,
  type NewBusiness,
  type NewLocation,
  type NewRegistration,
  type Onboarding,
  type OnboardingDto,
  type Prefill,
  type PrefillDto,
  type ProfileNode,
  type ProfileNodeDto,
  type Question,
  type QuestionDto,
  type RegistrationAddInDto,
  type RegistrationAdded,
  type RegistrationCreatedDto,
  type ReviewTask,
  type ReviewTaskDto,
  type Snapshot,
  type SnapshotDto,
  type ValueState,
} from "./types";

export function isValueState(value: string): value is ValueState {
  return (VALUE_STATES as readonly string[]).includes(value);
}

function bound(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

// ---- from the wire ---------------------------------------------------------------------------

export function attributeValueFromDto(dto: AttributeValueDto): AttributeValue {
  return {
    key: dto.key,
    state: dto.state,
    value: dto.value ?? null,
    asOfFy: dto.as_of_fy ?? null,
    source: dto.source,
    updatedAt: dto.updated_at ?? null,
  };
}

export function profileNodeFromDto(dto: ProfileNodeDto): ProfileNode {
  return {
    id: dto.id,
    level: dto.level,
    key: dto.key,
    name: dto.name,
    parentId: dto.parent_id ?? null,
    version: dto.version,
    attributes: dto.attributes.map(attributeValueFromDto),
    created: dto.created ?? false,
  };
}

export function businessFromDto(dto: BusinessDto): Business {
  return {
    id: dto.id,
    name: dto.name,
    pan: dto.pan,
    version: dto.version,
    createdAt: dto.created_at,
    updatedAt: dto.updated_at,
    attributes: dto.attributes.map(attributeValueFromDto),
    registrations: dto.registrations.map(profileNodeFromDto),
  };
}

export function businessSummaryFromDto(dto: BusinessSummaryDto): BusinessSummary {
  return {
    id: dto.id,
    name: dto.name,
    pan: dto.pan,
    gstins: [...dto.gstins],
    updatedAt: dto.updated_at,
  };
}

export function businessPageFromDto(dto: BusinessPageDto): BusinessPage {
  return {
    items: dto.items.map(businessSummaryFromDto),
    nextCursor: dto.next_cursor ?? null,
  };
}

export function questionFromDto(dto: QuestionDto): Question {
  return {
    nodeId: dto.node_id,
    level: dto.level,
    key: dto.key,
    state: dto.state,
    perFinancialYear: dto.per_financial_year,
    asOfFy: dto.as_of_fy ?? null,
    type: dto.type,
    question: dto.question,
    help: dto.help,
    options: dto.options.map((option) => ({ value: option.value, label: option.label })),
    min: bound(dto.min),
    max: bound(dto.max),
  };
}

export function onboardingFromDto(dto: OnboardingDto): Onboarding {
  return {
    businessId: dto.business_id,
    asOfFy: dto.as_of_fy,
    answered: dto.answered,
    total: dto.total,
    complete: dto.complete,
    next: dto.next === null || dto.next === undefined ? null : questionFromDto(dto.next),
  };
}

export function lookupResultFromDto(dto: LookupResultDto): LookupResult {
  return {
    gstin: dto.gstin,
    legalName: dto.legal_name,
    tradeName: dto.trade_name,
    registrationType: dto.registration_type,
    gstinStatus: dto.gstin_status,
    stateCode: dto.state_code,
    constitution: dto.constitution,
    registeredSince: dto.registered_since ?? null,
    businessCategory: dto.business_category ?? "",
    natureOfBusiness: [...(dto.nature_of_business ?? [])],
  };
}

export function prefillFromDto(dto: PrefillDto): Prefill {
  return {
    nodeId: dto.node_id,
    lookedUp: dto.looked_up,
    result:
      dto.result === null || dto.result === undefined ? null : lookupResultFromDto(dto.result),
    applied: [...dto.applied],
    reviewTaskId: dto.review_task ?? null,
  };
}

export function businessCreatedFromDto(dto: BusinessCreatedDto): BusinessCreated {
  return {
    business: businessFromDto(dto.business),
    created: dto.created,
    prefill: dto.prefill === null || dto.prefill === undefined ? null : prefillFromDto(dto.prefill),
    onboarding: onboardingFromDto(dto.onboarding),
  };
}

export function registrationAddedFromDto(dto: RegistrationCreatedDto): RegistrationAdded {
  return {
    business: businessFromDto(dto.business),
    registration: profileNodeFromDto(dto.registration),
    created: dto.created,
    prefill: prefillFromDto(dto.prefill),
  };
}

export function reviewTaskFromDto(dto: ReviewTaskDto): ReviewTask {
  return {
    id: dto.id,
    nodeId: dto.node_id,
    attributeKey: dto.attribute_key,
    reason: dto.reason,
    asOfFy: dto.as_of_fy ?? null,
    open: dto.open,
    createdAt: dto.created_at,
  };
}

export function snapshotFromDto(dto: SnapshotDto): Snapshot {
  return {
    businessId: dto.business_id,
    tenantId: dto.tenant_id,
    version: dto.version,
    level: dto.level ?? null,
    lineage: [...dto.lineage],
    asOfFy: dto.as_of_fy ?? null,
    attributes: { ...dto.attributes },
  };
}

// ---- to the wire -----------------------------------------------------------------------------

/**
 * One answer as the business API takes it. The value travels only with a known state (the
 * service refuses one on unsure and not_applicable), and the year and node only when set.
 */
export function answerToDto(answer: Answer): BusinessChangeInDto {
  const dto: BusinessChangeInDto = { key: answer.key, state: answer.state };
  if (answer.state === "known") dto.value = answer.value;
  if (answer.asOfFy !== undefined && answer.asOfFy !== null) dto.as_of_fy = answer.asOfFy;
  if (answer.nodeId !== undefined && answer.nodeId !== null) dto.node_id = answer.nodeId;
  return dto;
}

export function newBusinessToDto(input: NewBusiness): BusinessInDto {
  const dto: BusinessInDto = { name: input.name };
  if (input.gstin !== undefined && input.gstin !== "") dto.gstin = input.gstin;
  if (input.pan !== undefined && input.pan !== "") dto.pan = input.pan;
  if (input.registrationName !== undefined && input.registrationName !== "") {
    dto.registration_name = input.registrationName;
  }
  if (input.answers !== undefined && input.answers.length > 0) {
    // AnswerIn is BusinessChangeIn without node_id; a new business has no node to name yet.
    dto.answers = input.answers.map((answer) => answerToDto({ ...answer, nodeId: null }));
  }
  return dto;
}

export function businessChangesToDto(changes: BusinessChanges): BusinessPatchInDto {
  const dto: BusinessPatchInDto = {};
  if (changes.name !== undefined) dto.name = changes.name;
  if (changes.changes !== undefined) dto.changes = changes.changes.map(answerToDto);
  return dto;
}

export function newRegistrationToDto(input: NewRegistration): RegistrationAddInDto {
  const dto: RegistrationAddInDto = { gstin: input.gstin };
  if (input.name !== undefined && input.name !== "") dto.name = input.name;
  return dto;
}

export function newLocationToDto(input: NewLocation): LocationInDto {
  return { registration_id: input.registrationId, label: input.label, name: input.name };
}

// ---- lookups ---------------------------------------------------------------------------------

/**
 * The value a node holds for an attribute: the one for the given financial year when the
 * attribute is stated per year, else the one without a year.
 */
export function valueOf(
  values: readonly AttributeValue[],
  key: string,
  fy?: string | null,
): AttributeValue | undefined {
  const forKey = values.filter((value) => value.key === key);
  return (
    forKey.find((value) => value.asOfFy === (fy ?? null)) ?? forKey.find((v) => v.asOfFy === null)
  );
}
