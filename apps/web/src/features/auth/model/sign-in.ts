import { z } from "zod";
import { roleLabel } from "@/entities/screen/mappers";
import { ALLOWED_ROLES, TENANT_KINDS } from "@/shared/config/roles";
import type { Role, TenantKind } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import type { MessageKey } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";

/**
 * The development sign-in form's vocabulary and the shape check of what it posts. Semantics
 * (which roles a tenant kind allows, what a tenant id looks like) are the adapter's business
 * (server/auth/fake.ts); this module turns FormData into the typed input and builds the
 * options the form renders. The page computes the options and passes them as props, so the
 * client component imports nothing from here.
 */
export const FIELD_NAMES = {
  tenantKind: "tenantKind",
  roles: "roles",
  displayName: "displayName",
  tenantId: "tenantId",
  next: "next",
} as const;

export type SignInFieldNames = typeof FIELD_NAMES;

export const DEFAULT_TENANT_KIND: TenantKind = "business";

const KIND_MESSAGE_KEYS: Record<TenantKind, MessageKey> = {
  business: "tenantKind.business",
  ca_firm: "tenantKind.ca_firm",
  internal: "tenantKind.internal",
};

export function tenantKindMessageKey(kind: TenantKind): MessageKey {
  return KIND_MESSAGE_KEYS[kind];
}

export interface RoleOption {
  value: Role;
  label: string;
}

export interface KindOption {
  value: TenantKind;
  label: string;
}

/** The roles a tenant kind allows, as checkbox options in the registry's order. */
export function roleOptionsFor(kind: TenantKind): RoleOption[] {
  return ALLOWED_ROLES[kind].map((role) => ({ value: role, label: roleLabel(role) }));
}

export function isKnownTenantKind(value: string): value is TenantKind {
  return (TENANT_KINDS as readonly string[]).includes(value);
}

/** Everything the form renders from: the kinds, the roles per kind, the input names. */
export interface SignInFormOptions {
  fields: SignInFieldNames;
  defaultKind: TenantKind;
  kinds: readonly KindOption[];
  rolesByKind: Readonly<Record<TenantKind, readonly RoleOption[]>>;
}

export function signInFormOptions(): SignInFormOptions {
  return {
    fields: FIELD_NAMES,
    defaultKind: DEFAULT_TENANT_KIND,
    kinds: TENANT_KINDS.map((kind) => ({ value: kind, label: t(tenantKindMessageKey(kind)) })),
    rolesByKind: {
      business: roleOptionsFor("business"),
      ca_firm: roleOptionsFor("ca_firm"),
      internal: roleOptionsFor("internal"),
    },
  };
}

const text = z.string({ error: "Expected a text value." });

/** Shape only: strings where strings are expected, a list of roles; the adapter checks the rest. */
const formSchema = z.object({
  tenantKind: text,
  roles: z.array(text),
  displayName: text,
  tenantId: text.optional(),
  next: text.optional(),
});

export interface FakeSignInForm {
  tenantKind: string;
  roles: readonly string[];
  displayName: string;
  tenantId?: string;
  next?: string;
}

export type ParsedSignInForm =
  { ok: true; value: FakeSignInForm } | { ok: false; fieldErrors: FieldErrors };

function stringOrUndefined(value: FormDataEntryValue | null): unknown {
  if (value === null) return undefined;
  return value;
}

/** FormData to the typed form, or the fields whose values are not text. */
export function parseFakeSignInForm(formData: FormData): ParsedSignInForm {
  const parsed = formSchema.safeParse({
    tenantKind: formData.get(FIELD_NAMES.tenantKind) ?? "",
    roles: formData.getAll(FIELD_NAMES.roles),
    displayName: formData.get(FIELD_NAMES.displayName) ?? "",
    tenantId: stringOrUndefined(formData.get(FIELD_NAMES.tenantId)),
    next: stringOrUndefined(formData.get(FIELD_NAMES.next)),
  });
  if (parsed.success) {
    const { tenantId, next, ...rest } = parsed.data;
    const value: FakeSignInForm = { ...rest };
    if (tenantId !== undefined && tenantId.trim() !== "") value.tenantId = tenantId.trim();
    if (next !== undefined && next !== "") value.next = next;
    return { ok: true, value };
  }
  const fieldErrors: Record<string, string[]> = {};
  for (const issue of parsed.error.issues) {
    const field = String(issue.path[0] ?? "form");
    (fieldErrors[field] ??= []).push(issue.message);
  }
  return { ok: false, fieldErrors };
}

/**
 * The plain reason the sign-in page shows for a refusal trying again cannot fix, by the
 * problem type identity answers the session exchange with (the slug after the type's prefix).
 * The real sign-in's proxy maps the refusal with it; a tenant whose deletion is under way
 * (identity-tenant-deleting, 403) signs nobody in.
 */
const REFUSAL_KEYS: Readonly<Record<string, MessageKey>> = {
  "identity-tenant-deleting": "signIn.refusal.tenantDeleting",
};

/** The message key of a refusal's plain reason, or undefined for a problem it has none for. */
export function signInRefusalKey(slug: string): MessageKey | undefined {
  return Object.hasOwn(REFUSAL_KEYS, slug) ? REFUSAL_KEYS[slug] : undefined;
}
