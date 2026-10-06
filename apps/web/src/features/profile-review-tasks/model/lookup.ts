import {
  currentFinancialYear,
  financialYearLabel,
  parseFinancialYearLabel,
} from "@/shared/lib/financial-year";
import { isHexUuid } from "@/shared/lib/identifiers";
import { t } from "@/shared/i18n";
import { withQuery } from "@/shared/lib/url";

/**
 * The review task lookup's question, from its GET form: a tenant and one of its profile nodes (a
 * legal entity, a registration or a location), and the financial year the snapshot is for. The
 * profile routes act for the tenant named in x-tenant-id, so the lookup names it; ids and year
 * labels are not personal data, so the question sits in the address and can be shared.
 *
 *   tenant  the tenant's id
 *   node    the node's id
 *   fy      the snapshot's year as "2026-27"; this financial year when absent
 */
export const LOOKUP_PARAMS = { tenant: "tenant", node: "node", fy: "fy" } as const;

export type LookupField = "tenant" | "node" | "fy";

export type NodeLookup =
  | { kind: "empty"; fy: string }
  | {
      kind: "invalid";
      values: Record<LookupField, string>;
      errors: Partial<Record<LookupField, string>>;
    }
  | { kind: "ok"; tenantId: string; nodeId: string; fy: string };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(query: Query, key: string): string {
  const value = query[key];
  return ((Array.isArray(value) ? value[0] : value) ?? "").trim();
}

export function readLookup(query: Query, now: Date = new Date()): NodeLookup {
  const tenant = first(query, LOOKUP_PARAMS.tenant).toLowerCase();
  const node = first(query, LOOKUP_PARAMS.node).toLowerCase();
  const fyValue = first(query, LOOKUP_PARAMS.fy);
  const fy = fyValue === "" ? financialYearLabel(currentFinancialYear(now)) : fyValue;
  if (tenant === "" && node === "" && fyValue === "") return { kind: "empty", fy };
  const errors: Partial<Record<LookupField, string>> = {};
  if (!isHexUuid(tenant)) errors.tenant = t("profileReview.tenantInvalid");
  if (!isHexUuid(node)) errors.node = t("profileReview.nodeInvalid");
  if (parseFinancialYearLabel(fy) === null) errors.fy = t("profileReview.fyInvalid");
  if (Object.keys(errors).length > 0) {
    return { kind: "invalid", values: { tenant, node, fy: fyValue }, errors };
  }
  return { kind: "ok", tenantId: tenant, nodeId: node, fy };
}

/** The lookup's address for a node of the tenant, in a year. */
export function lookupHref(pathname: string, tenantId: string, nodeId: string, fy: string): string {
  return withQuery(pathname, {
    [LOOKUP_PARAMS.tenant]: tenantId,
    [LOOKUP_PARAMS.node]: nodeId,
    [LOOKUP_PARAMS.fy]: fy,
  });
}
