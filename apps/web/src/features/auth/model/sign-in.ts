import { z } from "zod";
import { roleLabel } from "@/entities/screen/mappers";
import { ALLOWED_ROLES, TENANT_KINDS } from "@/shared/config/roles";
import type { Role, TenantKind } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import type { MessageKey } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isE164, isEmailAddress } from "@/shared/lib/identifiers";

/**
 * The sign-in forms' vocabulary and the shape checks of what they post: the development
 * sign-in (a persona), the phone and code steps, the email link, the sign-up form and the
 * second-factor forms. Semantics (which roles a tenant kind allows, what a code is worth) are
 * the adapter's and identity's business; this module turns FormData into typed input and
 * builds the options the forms render. The pages compute the options and pass them as props,
 * so the client components import nothing from here.
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
 * The plain reason for a refusal trying again cannot fix, by the problem type identity answers
 * the session exchange with (the slug after the type's prefix): a disabled user
 * (identity-user-disabled, 403), a tenant whose deletion is under way
 * (identity-tenant-deleting, 403), a sign-up for a person who is a user already
 * (identity-subject-registered, 409).
 */
const REFUSAL_KEYS: Readonly<Record<string, MessageKey>> = {
  "identity-user-disabled": "signIn.refusal.userDisabled",
  "identity-tenant-deleting": "signIn.refusal.tenantDeleting",
  "identity-subject-registered": "signIn.refusal.subjectRegistered",
};

/** The message key of a refusal's plain reason, or undefined for a problem it has none for. */
export function signInRefusalKey(slug: string): MessageKey | undefined {
  return Object.hasOwn(REFUSAL_KEYS, slug) ? REFUSAL_KEYS[slug] : undefined;
}

// ---- The real sign-in: phone, code, email link, sign-up and the second factor -------------

export const SIGN_IN_FIELDS = {
  phone: "phone",
  code: "code",
  email: "email",
  next: "next",
} as const;

export type SignInStepFieldNames = typeof SIGN_IN_FIELDS;

export const SIGN_UP_FIELDS = { kind: "kind", name: "name", displayName: "displayName" } as const;

export type SignUpFieldNames = typeof SIGN_UP_FIELDS;

export const MFA_FIELDS = {
  code: "code",
  factorId: "factorId",
  friendlyName: "friendlyName",
  next: "next",
} as const;

export type MfaFieldNames = typeof MFA_FIELDS;

/** How long the code step waits before offering another code, in seconds. */
export const RESEND_AFTER_SECONDS = 30;

export const OTP_LENGTH = 6;

export const SIGN_UP_KINDS = ["business", "ca_firm"] as const;

export type SignUpKind = (typeof SIGN_UP_KINDS)[number];

export const TENANT_NAME_MAX_LENGTH = 200;

/** The sign-in methods a page may show, as the `method` query names them. */
export type SignInMethodName = "dev" | "phone" | "email";

const METHOD_NAMES: readonly SignInMethodName[] = ["dev", "phone", "email"];

/** The method to show: the query's when the provider offers it, else the first on offer. */
export function readSignInMethod(
  value: string | string[] | undefined,
  available: readonly SignInMethodName[],
): SignInMethodName {
  const wanted = typeof value === "string" ? value : undefined;
  if (wanted !== undefined && (METHOD_NAMES as readonly string[]).includes(wanted)) {
    if (available.includes(wanted as SignInMethodName)) return wanted as SignInMethodName;
  }
  return available[0] ?? "phone";
}

/** What the sign-in page says above the form, from its `reason` and `error` queries. */
const NOTICE_KEYS: Readonly<Record<string, MessageKey>> = {
  "reason:signed-out": "signIn.notice.signedOut",
  "error:link-expired": "signIn.notice.linkExpired",
  "error:registered": "signIn.refusal.subjectRegistered",
  "error:disabled": "signIn.refusal.userDisabled",
  "error:tenant-deleting": "signIn.refusal.tenantDeleting",
  "error:pending-expired": "signIn.notice.pendingExpired",
};

export function signInNoticeKey(query: {
  reason?: string | string[] | undefined;
  error?: string | string[] | undefined;
}): MessageKey | undefined {
  for (const [name, value] of [
    ["reason", query.reason],
    ["error", query.error],
  ] as const) {
    if (typeof value !== "string") continue;
    const key = NOTICE_KEYS[`${name}:${value}`];
    if (key !== undefined) return key;
  }
  return undefined;
}

export type ParsedForm<T> = { ok: true; value: T } | { ok: false; fieldErrors: FieldErrors };

function stringField(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function optionalNext(formData: FormData): { next?: string } {
  const next = stringField(formData, SIGN_IN_FIELDS.next);
  return next === "" ? {} : { next };
}

/** A phone number as typed: spaces and dashes dropped, a 10-digit Indian number given +91. */
export function normaliseSignInPhone(value: string): string {
  const compact = value.replace(/[\s\-().]/g, "");
  if (/^[6-9][0-9]{9}$/.test(compact)) return `+91${compact}`;
  if (/^0[6-9][0-9]{9}$/.test(compact)) return `+91${compact.slice(1)}`;
  return compact;
}

export interface PhoneForm {
  phone: string;
  next?: string;
}

export function parsePhoneForm(formData: FormData): ParsedForm<PhoneForm> {
  const phone = normaliseSignInPhone(stringField(formData, SIGN_IN_FIELDS.phone));
  if (phone === "") return { ok: false, fieldErrors: { phone: [t("signIn.phoneRequired")] } };
  if (!isE164(phone)) return { ok: false, fieldErrors: { phone: [t("signIn.phoneInvalid")] } };
  return { ok: true, value: { phone, ...optionalNext(formData) } };
}

export interface CodeForm extends PhoneForm {
  code: string;
}

export function parseCodeForm(formData: FormData): ParsedForm<CodeForm> {
  const phone = parsePhoneForm(formData);
  if (!phone.ok) return phone;
  const code = stringField(formData, SIGN_IN_FIELDS.code).replace(/\s/g, "");
  if (!new RegExp(`^[0-9]{${OTP_LENGTH}}$`).test(code)) {
    return { ok: false, fieldErrors: { code: [t("signIn.codeInvalid", { length: OTP_LENGTH })] } };
  }
  return { ok: true, value: { ...phone.value, code } };
}

export interface EmailForm {
  email: string;
  next?: string;
}

export function parseEmailForm(formData: FormData): ParsedForm<EmailForm> {
  const email = stringField(formData, SIGN_IN_FIELDS.email).trim().toLowerCase();
  if (email === "") return { ok: false, fieldErrors: { email: [t("signIn.emailRequired")] } };
  if (!isEmailAddress(email)) {
    return { ok: false, fieldErrors: { email: [t("signIn.emailInvalid")] } };
  }
  return { ok: true, value: { email, ...optionalNext(formData) } };
}

export interface SignUpForm {
  kind: SignUpKind;
  name: string;
  displayName: string;
}

export function parseSignUpForm(formData: FormData): ParsedForm<SignUpForm> {
  const errors: Record<string, string[]> = {};
  const kind = stringField(formData, SIGN_UP_FIELDS.kind);
  if (!(SIGN_UP_KINDS as readonly string[]).includes(kind))
    errors.kind = [t("signUp.kindRequired")];
  const name = stringField(formData, SIGN_UP_FIELDS.name).trim();
  if (name === "") errors.name = [t("signUp.nameRequired")];
  else if (name.length > TENANT_NAME_MAX_LENGTH) {
    errors.name = [t("signUp.nameTooLong", { max: TENANT_NAME_MAX_LENGTH })];
  }
  const displayName = stringField(formData, SIGN_UP_FIELDS.displayName).trim();
  if (displayName.length > TENANT_NAME_MAX_LENGTH) {
    errors.displayName = [t("signUp.nameTooLong", { max: TENANT_NAME_MAX_LENGTH })];
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return { ok: true, value: { kind: kind as SignUpKind, name, displayName } };
}

export interface MfaForm {
  code: string;
  factorId?: string;
  friendlyName?: string;
  next?: string;
}

/** The second-factor forms: a code (optional for the confirm step), the factor it is for. */
export function parseMfaForm(formData: FormData, options: { code: boolean }): ParsedForm<MfaForm> {
  const code = stringField(formData, MFA_FIELDS.code).replace(/\s/g, "");
  if (options.code && !new RegExp(`^[0-9]{${OTP_LENGTH}}$`).test(code)) {
    return { ok: false, fieldErrors: { code: [t("signIn.codeInvalid", { length: OTP_LENGTH })] } };
  }
  const value: MfaForm = { code };
  const factorId = stringField(formData, MFA_FIELDS.factorId).trim();
  if (factorId !== "") value.factorId = factorId;
  const friendlyName = stringField(formData, MFA_FIELDS.friendlyName).trim();
  if (friendlyName !== "") value.friendlyName = friendlyName.slice(0, 80);
  const next = stringField(formData, MFA_FIELDS.next);
  if (next !== "") value.next = next;
  return { ok: true, value };
}
