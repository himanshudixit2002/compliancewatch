import { isDateKey } from "@/shared/lib/dates";
import { withQuery } from "@/shared/lib/url";

/**
 * What the rule version list shows, from its query string (rule keys and dates are not personal
 * data, so a filtered list can be shared and bookmarked).
 *
 *   status  in_force (the default): the versions in force on `as_of`, published or superseded,
 *           from GET /v1/rulebook/rule-versions; or one status (draft, in_review, approved,
 *           published, superseded, withdrawn) or every status, from each rule's versions
 *   as_of   the date the in-force list is for, YYYY-MM-DD; today in IST when absent
 *   rule    one rule key, or every rule
 *   after   the keyset cursor: continue after this rule key
 */
export const LIST_STATUSES = [
  "in_force",
  "draft",
  "in_review",
  "approved",
  "published",
  "superseded",
  "withdrawn",
  "all",
] as const;

export type ListStatus = (typeof LIST_STATUSES)[number];

export const DEFAULT_LIST_STATUS: ListStatus = "in_force";

/** The query keys the list reads and the filter form posts. */
export const LIST_PARAMS = {
  status: "status",
  asOf: "as_of",
  rule: "rule",
  after: "after",
} as const;

/** A rule key as the rulebook writes them (`^[a-z][a-z0-9_]*$`, at most 80 characters). */
const RULE_KEY = /^[a-z][a-z0-9_]{0,79}$/;

export function isRuleKey(value: string): boolean {
  return RULE_KEY.test(value);
}

export function isListStatus(value: string): value is ListStatus {
  return (LIST_STATUSES as readonly string[]).includes(value);
}

export interface VersionListFilter {
  status: ListStatus;
  asOf: string;
  /** True when the date came from the query rather than today's default. */
  asOfGiven: boolean;
  ruleKey: string | null;
  after: string | null;
}

export type FilterField = "asOf" | "rule";

export interface ListFilterRead {
  filter: VersionListFilter;
  /** A value the list cannot use, with what was typed; nothing is read while one is present. */
  invalid: Partial<Record<FilterField, string>>;
}

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string | undefined {
  const value = query[key];
  const one = Array.isArray(value) ? value[0] : value;
  return one === undefined ? undefined : one.trim();
}

/** The filter from the query; `today` is today's IST date key, the default as-of date. */
export function readListFilter(query: Query, today: string): ListFilterRead {
  const invalid: Partial<Record<FilterField, string>> = {};
  const status = first(query, LIST_PARAMS.status) ?? "";
  const asOf = first(query, LIST_PARAMS.asOf) ?? "";
  const rule = first(query, LIST_PARAMS.rule) ?? "";
  const after = first(query, LIST_PARAMS.after) ?? "";
  if (asOf !== "" && !isDateKey(asOf)) invalid.asOf = asOf;
  if (rule !== "" && !isRuleKey(rule)) invalid.rule = rule;
  return {
    filter: {
      status: isListStatus(status) ? status : DEFAULT_LIST_STATUS,
      asOf: asOf !== "" && invalid.asOf === undefined ? asOf : today,
      asOfGiven: asOf !== "" && invalid.asOf === undefined,
      ruleKey: rule !== "" && invalid.rule === undefined ? rule : null,
      after: after !== "" && isRuleKey(after) ? after : null,
    },
    invalid,
  };
}

/**
 * The list's href for a filter: the default status and today's date are left out, and a page
 * cursor is kept only when one is given, so a chip or the filter form starts from the first page.
 */
export function listHref(
  pathname: string,
  filter: Pick<VersionListFilter, "status" | "asOf" | "asOfGiven" | "ruleKey">,
  after?: string,
): string {
  return withQuery(pathname, {
    [LIST_PARAMS.status]: filter.status === DEFAULT_LIST_STATUS ? undefined : filter.status,
    [LIST_PARAMS.asOf]: filter.status === "in_force" && filter.asOfGiven ? filter.asOf : undefined,
    [LIST_PARAMS.rule]: filter.ruleKey ?? undefined,
    [LIST_PARAMS.after]: after,
  });
}
