import type { ReviewStatus } from "@/entities/applicability/types";
import { t, type MessageKey } from "@/shared/i18n";
import { isUuid } from "@/shared/lib/identifiers";
import { withQuery } from "@/shared/lib/url";

/**
 * The decision review's lookup. The review routes act for the tenant named in x-tenant-id: on
 * these two routes alone a regulatory user names the tenant reviewed rather than their own (the
 * engine's documented cross-tenant exception). The screen therefore asks for the tenant by id, in
 * the query string (an id is not personal data, so a lookup can be shared), with the status to
 * list and the engine's cursor.
 */
export const LOOKUP_FIELDS = { tenant: "tenant", status: "status", cursor: "cursor" } as const;

/** The items to list: the open ones (the default), the resolved ones, or every item. */
export type StatusFilter = ReviewStatus | "all";

export const STATUS_FILTERS: readonly StatusFilter[] = ["open", "resolved", "all"];

const STATUS_LABEL: Readonly<Record<StatusFilter, MessageKey>> = {
  open: "decisions.filter.open",
  resolved: "decisions.filter.resolved",
  all: "decisions.filter.all",
};

export function statusFilterLabel(status: StatusFilter): string {
  return t(STATUS_LABEL[status]);
}

export function isStatusFilter(value: string): value is StatusFilter {
  return (STATUS_FILTERS as readonly string[]).includes(value);
}

export type DecisionLookup =
  | { kind: "empty"; status: StatusFilter }
  | { kind: "invalid"; value: string; error: string; status: StatusFilter }
  | { kind: "ok"; tenantId: string; status: StatusFilter; cursor: string | null };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

function cursorOf(value: string): string | null {
  if (value === "" || value.length > 512) return null;
  return /^[A-Za-z0-9_-]+$/.test(value) ? value : null;
}

/** The tenant, the status and the page the screen was asked for, or what is wrong with them. */
export function readDecisionLookup(query: Query): DecisionLookup {
  const statusText = first(query[LOOKUP_FIELDS.status]);
  const status: StatusFilter = isStatusFilter(statusText) ? statusText : "open";
  const tenant = first(query[LOOKUP_FIELDS.tenant]).toLowerCase();
  if (tenant === "") return { kind: "empty", status };
  if (!isUuid(tenant)) {
    return { kind: "invalid", value: tenant, error: t("decisions.error.tenant"), status };
  }
  return {
    kind: "ok",
    tenantId: tenant,
    status,
    cursor: cursorOf(first(query[LOOKUP_FIELDS.cursor])),
  };
}

/** The screen's address for a tenant and a status (the default status is left out). */
export function lookupHref(
  pathname: string,
  tenantId: string,
  status: StatusFilter,
  cursor?: string,
): string {
  return withQuery(pathname, {
    [LOOKUP_FIELDS.tenant]: tenantId,
    [LOOKUP_FIELDS.status]: status === "open" ? undefined : status,
    [LOOKUP_FIELDS.cursor]: cursor,
  });
}
