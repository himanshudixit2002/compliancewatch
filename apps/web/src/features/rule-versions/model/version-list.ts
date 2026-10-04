import type { RuleSummary, RuleVersion } from "@/entities/rule-version/types";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t, type MessageKey } from "@/shared/i18n";
import { LIST_STATUSES, listHref, type ListStatus, type VersionListFilter } from "./list-filter";

/** Rows on one page of the in-force list; the status lists fill a page rule by rule. */
export const PAGE_SIZE = 25;

/** How many rules' versions the status lists read at once. */
export const RULE_BATCH = 8;

export interface VersionRow {
  ruleVersionId: string;
  href: string;
  ruleKey: string;
  version: number;
  title: string;
  status: string;
  seedStatus: string;
  needsReview: boolean;
  effectiveFrom: string;
  effectiveTo: string | null;
  highImpact: boolean;
  /** The analyst questions still on the version. */
  openQuestions: number;
  publishedAt: string | null;
}

export interface StatusChip {
  status: ListStatus;
  label: string;
  href: string;
  current: boolean;
}

export interface RuleOption {
  value: string;
  label: string;
}

export interface VersionListView {
  filter: VersionListFilter;
  rows: readonly VersionRow[];
  /** The next page (keyset by rule key), or null on the last one. */
  nextHref: string | null;
  /** Back to the first page from a later one, or null on the first. */
  firstHref: string | null;
  rules: readonly RuleOption[];
}

const CHIP_LABELS: Readonly<Record<ListStatus, MessageKey>> = {
  in_force: "ruleVersions.chip.in_force",
  draft: "ruleVersions.chip.draft",
  in_review: "ruleVersions.chip.in_review",
  approved: "ruleVersions.chip.approved",
  published: "ruleVersions.chip.published",
  superseded: "ruleVersions.chip.superseded",
  withdrawn: "ruleVersions.chip.withdrawn",
  all: "ruleVersions.chip.all",
};

export function statusChipLabel(status: ListStatus): string {
  return t(CHIP_LABELS[status]);
}

/** One chip per status, each starting from the first page with the other filters kept. */
export function statusChips(pathname: string, filter: VersionListFilter): StatusChip[] {
  return LIST_STATUSES.map((status) => ({
    status,
    label: statusChipLabel(status),
    href: listHref(pathname, { ...filter, status }),
    current: status === filter.status,
  }));
}

export function versionHref(ruleVersionId: string): string {
  return hrefFor(screenById("admin.rulebook.version"), { ruleVersionId });
}

export function versionRow(version: RuleVersion): VersionRow {
  return {
    ruleVersionId: version.ruleVersionId,
    href: versionHref(version.ruleVersionId),
    ruleKey: version.ruleKey,
    version: version.version,
    title: version.title,
    status: version.status,
    seedStatus: version.seedStatus,
    needsReview: version.needsReview,
    effectiveFrom: version.effectiveFrom,
    effectiveTo: version.effectiveTo,
    highImpact: version.highImpact,
    openQuestions: version.todo.length,
    publishedAt: version.publishedAt,
  };
}

/** The versions a status chip keeps: one status, or every one. */
export function inStatus(
  versions: readonly RuleVersion[],
  status: Exclude<ListStatus, "in_force">,
): RuleVersion[] {
  return status === "all" ? [...versions] : versions.filter((version) => version.status === status);
}

/** Rule keys in the order the rulebook pages them: by code point, as `after` compares them. */
export function byRuleKey(a: { ruleKey: string }, b: { ruleKey: string }): number {
  return a.ruleKey < b.ruleKey ? -1 : a.ruleKey > b.ruleKey ? 1 : 0;
}

/** Rules for the filter's select, by key, each named by its latest title. */
export function ruleOptions(rules: readonly RuleSummary[]): RuleOption[] {
  return [...rules]
    .sort(byRuleKey)
    .map((rule) => ({ value: rule.ruleKey, label: `${rule.ruleKey}: ${rule.title}` }));
}
