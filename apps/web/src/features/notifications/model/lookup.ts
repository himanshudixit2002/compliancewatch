import { t } from "@/shared/i18n";
import { isUuid } from "@/shared/lib/identifiers";

/**
 * The admin console's lookup. The notification routes are tenant-scoped: a request names one
 * tenant in x-tenant-id and sees only that tenant's notifications, of one business at a time. The
 * console therefore asks for the tenant and the business by id, in the query string (ids, not
 * personal data), and the gateway acts for that tenant. A notification opened on its own carries
 * the tenant the same way (`?tenant=`).
 */
export const LOOKUP_FIELDS = { tenant: "tenant", business: "business" } as const;

export interface AdminLookup {
  tenantId: string;
  businessId: string;
}

export type LookupField = keyof typeof LOOKUP_FIELDS;

export type LookupRead =
  | { kind: "empty" }
  | {
      kind: "invalid";
      values: Record<LookupField, string>;
      errors: Partial<Record<LookupField, string>>;
    }
  | { kind: "ok"; lookup: AdminLookup };

type Query = Readonly<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value)?.trim() ?? "";
}

/** The tenant and the business the console was asked for, or what is wrong with them. */
export function readLookup(query: Query): LookupRead {
  const values = {
    tenant: first(query[LOOKUP_FIELDS.tenant]).toLowerCase(),
    business: first(query[LOOKUP_FIELDS.business]).toLowerCase(),
  };
  if (values.tenant === "" && values.business === "") return { kind: "empty" };
  const errors: Partial<Record<LookupField, string>> = {};
  if (!isUuid(values.tenant)) errors.tenant = t("adminNotifications.error.tenant");
  if (!isUuid(values.business)) errors.business = t("adminNotifications.error.business");
  if (Object.keys(errors).length > 0) return { kind: "invalid", values, errors };
  return { kind: "ok", lookup: { tenantId: values.tenant, businessId: values.business } };
}

export type TenantRead =
  | { kind: "empty" }
  | { kind: "invalid"; value: string; error: string }
  | { kind: "ok"; tenantId: string };

/** The tenant a notification opened on its own belongs to. */
export function readTenant(query: Query): TenantRead {
  const value = first(query[LOOKUP_FIELDS.tenant]).toLowerCase();
  if (value === "") return { kind: "empty" };
  if (!isUuid(value))
    return { kind: "invalid", value, error: t("adminNotifications.error.tenant") };
  return { kind: "ok", tenantId: value };
}
