import type { ChangeImpactDto } from "@/entities/applicability/types";
import type { RuleChangeDto, RuleChangePageDto } from "@/entities/change/types";
import {
  APPROVER_IDS,
  CLAUSE_ID,
  DOCUMENT_ID,
  ENTITY_ID,
  REGISTRATION_ID,
} from "./obligation-fixture";

/**
 * Changes feed and change impact bodies for unit tests: synthetic text, dates in 2000. The e2e
 * suite reads the real feed.
 */
export const CHANGE_ID = "00000000-0000-4000-8000-00000000c0c1";
export const CHANGED_VERSION_ID = "00000000-0000-4000-8000-00000000c0d1";

export function ruleChangeDto(overrides: Partial<RuleChangeDto> = {}): RuleChangeDto {
  return {
    change_id: CHANGE_ID,
    kind: "published",
    changed_at: "2000-01-05T04:30:00Z",
    rule_version_id: CHANGED_VERSION_ID,
    rule_key: "example_rule",
    title: "Example rule 2",
    summary: "Example summary of the rule.",
    version: 2,
    regulator: "Example regulator",
    level: "registration",
    status: "published",
    effective_from: "2000-01-01",
    effective_to: null,
    seed_status: "needs_review",
    approved_by: [...APPROVER_IDS],
    published_at: "2000-01-05T04:30:00Z",
    citations: [
      {
        clause_id: CLAUSE_ID,
        document_id: DOCUMENT_ID,
        clause_ref: "en.p2",
        quote: "Example quoted clause text.",
      },
    ],
    caused_by_rule_version_id: null,
    deadline: null,
    relations: { supersedes: [], corrects: [], withdraws: [], extends_deadline: [] },
    ...overrides,
  };
}

export function ruleChangePageDto(
  items: RuleChangeDto[],
  nextCursor: string | null = null,
): RuleChangePageDto {
  return { items, next_cursor: nextCursor };
}

export function changeImpactDto(
  results: {
    entityId?: string;
    businessId?: string;
    result: "applies" | "not_applicable" | "unsure";
  }[] = [{ result: "applies" }],
  overrides: Partial<ChangeImpactDto> = {},
): ChangeImpactDto {
  const byEntity = new Map<string, ChangeImpactDto["items"][number]>();
  for (const [index, entry] of results.entries()) {
    const entityId = entry.entityId ?? ENTITY_ID;
    const group = byEntity.get(entityId) ?? { entity_id: entityId, businesses: [] };
    group.businesses.push({
      business_id: entry.businessId ?? REGISTRATION_ID,
      level: "registration",
      decision_id: `00000000-0000-4000-8000-0000000d${String(index).padStart(4, "0")}`,
      result: entry.result,
      confidence: entry.result === "unsure" ? 0.5 : 1,
      needs_review: entry.result === "unsure",
      profile_version: 1,
      as_of_fy: null,
      trigger: "rule_published",
      decided_at: "2000-01-05T05:00:00Z",
      evaluated: [],
    });
    byEntity.set(entityId, group);
  }
  return {
    rule_version_id: CHANGED_VERSION_ID,
    counts: { applies: 0, not_applicable: 0, unsure: 0 },
    fan_out: null,
    items: [...byEntity.values()],
    next_cursor: null,
    ...overrides,
  };
}
