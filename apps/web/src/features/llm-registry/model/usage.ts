import { LLM_FEATURES, type LlmFeature, type Usage } from "@/entities/llm/types";
import { t } from "@/shared/i18n";
import { formatDateTime } from "@/shared/lib/dates";
import { ratioPercent } from "@/shared/lib/decimal";
import { isHexUuid } from "@/shared/lib/identifiers";
import { formatDecimalRupees } from "@/shared/lib/money";
import { featureLabel } from "./registry";

/**
 * The spend page's question, from its GET form (ids and feature names are not personal data):
 *
 *   tenant   a tenant's monthly budget (the feature, when given, narrows the sum)
 *   feature  a feature's monthly budget, when no tenant is named
 *   month    YYYY-MM in UTC, the gateway's month; this month when absent
 *
 * With neither a tenant nor a feature the page shows every feature's budget for the month, one
 * read each. Money stays decimal text: the ledger keeps fractions of a paisa, which the page
 * shows rather than rounding a small spend to nothing.
 */
export const USAGE_PARAMS = { tenant: "tenant", feature: "feature", month: "month" } as const;

const MONTH = /^2\d{3}-(0[1-9]|1[0-2])$/;

export type UsageField = "tenant" | "feature" | "month";

export type UsageRead =
  | { kind: "overview"; month: string }
  | { kind: "one"; month: string; tenantId?: string; feature?: LlmFeature }
  | {
      kind: "invalid";
      values: Record<UsageField, string>;
      errors: Partial<Record<UsageField, string>>;
    };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

function isFeature(value: string): value is LlmFeature {
  return (LLM_FEATURES as readonly string[]).includes(value);
}

/** This month in UTC, as the gateway counts months: 2000-01. */
export function currentMonth(now: Date = new Date()): string {
  return now.toISOString().slice(0, 7);
}

export function readUsage(query: Query, now: Date = new Date()): UsageRead {
  const tenant = first(query, USAGE_PARAMS.tenant).toLowerCase();
  const feature = first(query, USAGE_PARAMS.feature);
  const monthValue = first(query, USAGE_PARAMS.month);
  const month = monthValue === "" ? currentMonth(now) : monthValue;
  const errors: Partial<Record<UsageField, string>> = {};
  if (tenant !== "" && !isHexUuid(tenant)) errors.tenant = t("llm.usage.tenantInvalid");
  if (feature !== "" && !isFeature(feature)) errors.feature = t("llm.usage.featureInvalid");
  if (!MONTH.test(month)) errors.month = t("llm.usage.monthInvalid");
  if (Object.keys(errors).length > 0) {
    return { kind: "invalid", values: { tenant, feature, month: monthValue }, errors };
  }
  if (tenant === "" && feature === "") return { kind: "overview", month };
  return {
    kind: "one",
    month,
    ...(tenant === "" ? {} : { tenantId: tenant }),
    ...(isFeature(feature) ? { feature } : {}),
  };
}

const MONTH_NAMES = new Intl.DateTimeFormat("en-IN", {
  month: "long",
  year: "numeric",
  timeZone: "UTC",
});

/** "2000-01" as "January 2000". */
export function monthLabel(month: string): string {
  if (!MONTH.test(month)) return month;
  return MONTH_NAMES.format(new Date(`${month}-01T00:00:00Z`));
}

export interface UsageRow {
  key: string;
  scopeLabel: string;
  /** The feature's name, or the tenant's id. */
  keyLabel: string;
  /** "Spent", or "Spent on QA" when a feature narrows a tenant's spend. */
  spentLabel: string;
  /**
   * Set when a feature narrows a tenant's spend: the spend is that feature's alone, the budget the
   * tenant's for every feature, and the share and the alarm compare the two.
   */
  note: string | null;
  spent: string;
  budget: string;
  /** "6.17%" of the budget spent. */
  percent: string;
  /** The share for the bar, 0 to 100 (a spend over the budget fills it). */
  barValue: number;
  alarmed: boolean;
  resetsAt: string;
}

/**
 * One budget as its card shows it. `narrowedTo` is the feature that narrowed a tenant's spend:
 * the gateway then sums that feature's spend alone against the tenant's whole budget (and decides
 * the alarm on that sum), so the card says so in its label rather than read as the tenant's spend.
 */
export function usageRow(usage: Usage, narrowedTo?: LlmFeature): UsageRow {
  const percent = ratioPercent(usage.ratio);
  const narrowed =
    usage.scope === "tenant" && narrowedTo !== undefined ? featureLabel(narrowedTo) : null;
  return {
    key: `${usage.scope}:${usage.key}`,
    scopeLabel:
      narrowed !== null
        ? t("llm.usage.scope.tenantFeature", { feature: narrowed })
        : usage.scope === "tenant"
          ? t("llm.usage.scope.tenant")
          : t("llm.usage.scope.feature"),
    keyLabel: usage.scope === "feature" ? featureLabel(usage.key) : usage.key,
    spentLabel:
      narrowed === null ? t("llm.usage.spent") : t("llm.usage.spentOn", { feature: narrowed }),
    note: narrowed === null ? null : t("llm.usage.narrowedNote", { feature: narrowed }),
    spent: formatDecimalRupees(usage.spentInr),
    budget: formatDecimalRupees(usage.budgetInr),
    percent: `${percent}%`,
    barValue: Math.min(Math.max(Number(percent), 0), 100),
    alarmed: usage.alarmed,
    resetsAt: formatDateTime(usage.resetsAt),
  };
}

/** The feature select's options: none (every feature, or the tenant's whole spend), then each. */
export function featureOptions(): { value: string; label: string }[] {
  return [
    { value: "", label: t("llm.usage.everyFeature") },
    ...LLM_FEATURES.map((value) => ({ value, label: featureLabel(value) })),
  ];
}
