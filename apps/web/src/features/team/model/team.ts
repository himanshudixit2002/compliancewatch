import type { Tone } from "@compliancewatch/ui";
import type { identity } from "@compliancewatch/contracts/openapi";
import {
  ALLOWED_ROLES,
  MFA_REQUIRED_ROLES,
  TENANT_ADMIN_ROLES,
  isRole,
} from "@/shared/config/roles";
import type { Role, TenantKind } from "@/shared/config/roles";
import { t } from "@/shared/i18n";
import type { MessageKey } from "@/shared/i18n";
import type { FieldErrors } from "@/shared/lib/action-state";
import { isE164, isEmailAddress, normalisePhone } from "@/shared/lib/identifiers";

/**
 * The team screen's model: the people with access to the tenant as `GET /v1/identity/users`
 * returns them, with the labels and tones the table and the summary row use.
 */
export type UserDto = identity.components["schemas"]["UserOut"];
export type MemberStatus = identity.components["schemas"]["UserStatus"];

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  phone: string;
  roles: readonly Role[];
  status: MemberStatus;
  /** When the user was added, an ISO instant. */
  joinedAt: string;
}

export interface TeamSummary {
  total: number;
  active: number;
  disabled: number;
}

export const ROLE_LABEL: Readonly<Record<Role, MessageKey>> = {
  owner: "role.owner",
  staff: "role.staff",
  ca_admin: "role.ca_admin",
  ca_staff: "role.ca_staff",
  compliance_lead: "role.compliance_lead",
  analyst: "role.analyst",
  reviewer: "role.reviewer",
  admin: "role.admin",
};

/** Roles that manage the tenant stand out; the rest read as neutral. */
export const ROLE_TONE: Readonly<Record<Role, Tone>> = {
  owner: "info",
  ca_admin: "info",
  admin: "info",
  compliance_lead: "warning",
  staff: "neutral",
  ca_staff: "neutral",
  analyst: "neutral",
  reviewer: "neutral",
};

export const STATUS_LABEL: Readonly<Record<MemberStatus, MessageKey>> = {
  active: "team.status.active",
  disabled: "team.status.disabled",
};

export const STATUS_TONE: Readonly<Record<MemberStatus, Tone>> = {
  active: "success",
  disabled: "danger",
};

export function teamMemberFromDto(dto: UserDto): TeamMember {
  return {
    id: dto.id,
    name: dto.display_name,
    email: dto.email,
    phone: dto.phone,
    roles: dto.roles,
    status: dto.status,
    joinedAt: dto.created_at,
  };
}

/** Active members first, then by name. */
export function sortMembers(members: readonly TeamMember[]): TeamMember[] {
  return [...members].sort((a, b) => {
    if (a.status !== b.status) return a.status === "active" ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
}

export function teamSummary(members: readonly TeamMember[]): TeamSummary {
  const active = members.filter((member) => member.status === "active").length;
  return { total: members.length, active, disabled: members.length - active };
}

// ---- Management: the forms and their vocabulary --------------------------------------------

export const TEAM_FIELDS = {
  screen: "screen",
  userId: "userId",
  contact: "contact",
  displayName: "displayName",
  roles: "roles",
  reason: "reason",
} as const;

export type TeamFieldNames = typeof TEAM_FIELDS;

/** The two screens the management actions serve; the hidden field names one of them. */
export const TEAM_SCREEN_IDS = ["owner.settings.team", "admin.team"] as const;

export type TeamScreenId = (typeof TEAM_SCREEN_IDS)[number];

export function isTeamScreenId(value: string): value is TeamScreenId {
  return (TEAM_SCREEN_IDS as readonly string[]).includes(value);
}

export interface RoleOption {
  value: Role;
  label: string;
  /** The role signs in with a second factor; the internal page says so per role. */
  needsMfa: boolean;
}

/** The roles a tenant of this kind may give, as the invite and roles forms offer them. */
export function roleOptionsFor(kind: TenantKind): RoleOption[] {
  return ALLOWED_ROLES[kind].map((role) => ({
    value: role,
    label: t(ROLE_LABEL[role]),
    needsMfa: MFA_REQUIRED_ROLES.includes(role),
  }));
}

/** The admin roles of a tenant kind: owner, CA admin, or admin in the internal tenant. */
export function adminRolesFor(kind: TenantKind): readonly Role[] {
  const admins: readonly Role[] = kind === "internal" ? ["admin"] : TENANT_ADMIN_ROLES;
  return ALLOWED_ROLES[kind].filter((role) => admins.includes(role));
}

/**
 * Whether the member is the tenant's only active admin, as the page can tell: a hint for the
 * forms, so they can say why a change may be refused; identity's 409 is the authority.
 */
export function isLastAdmin(
  members: readonly TeamMember[],
  userId: string,
  kind: TenantKind,
): boolean {
  const admins = adminRolesFor(kind);
  const active = members.filter(
    (member) => member.status === "active" && member.roles.some((role) => admins.includes(role)),
  );
  return active.length === 1 && active[0]?.id === userId;
}

export type ParsedForm<T> = { ok: true; value: T } | { ok: false; fieldErrors: FieldErrors };

function stringField(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

function rolesField(formData: FormData, kind: TenantKind): { roles: Role[]; error?: string } {
  const given = formData
    .getAll(TEAM_FIELDS.roles)
    .filter((v): v is string => typeof v === "string");
  const roles = given.filter(isRole);
  if (roles.length === 0) return { roles: [], error: t("team.form.rolesRequired") };
  const refused = roles.filter((role) => !ALLOWED_ROLES[kind].includes(role));
  if (refused.length > 0) {
    return { roles: [], error: t("team.form.rolesNotAllowed", { roles: refused.join(", ") }) };
  }
  return { roles: ALLOWED_ROLES[kind].filter((role) => roles.includes(role)) };
}

export interface InviteForm {
  screen: TeamScreenId;
  contact: { email?: string; phone?: string };
  displayName: string;
  roles: Role[];
}

/** The invite form: one contact (an email address or a mobile number), a name, the roles. */
export function parseInviteForm(formData: FormData, kind: TenantKind): ParsedForm<InviteForm> {
  const errors: Record<string, string[]> = {};
  const screen = stringField(formData, TEAM_FIELDS.screen);
  if (!isTeamScreenId(screen)) errors.screen = [t("team.form.screenUnknown")];
  const raw = stringField(formData, TEAM_FIELDS.contact).trim();
  const contact: InviteForm["contact"] = {};
  if (raw === "") errors.contact = [t("team.form.contactRequired")];
  else if (raw.includes("@")) {
    const email = raw.toLowerCase();
    if (!isEmailAddress(email)) errors.contact = [t("team.form.contactInvalid")];
    else contact.email = email;
  } else {
    const phone = normalisePhone(raw);
    const number = /^[6-9][0-9]{9}$/.test(phone) ? `+91${phone}` : phone;
    if (!isE164(number)) errors.contact = [t("team.form.contactInvalid")];
    else contact.phone = number;
  }
  const displayName = stringField(formData, TEAM_FIELDS.displayName).trim();
  if (displayName.length > 200) errors.displayName = [t("team.form.nameTooLong")];
  const roles = rolesField(formData, kind);
  if (roles.error !== undefined) errors.roles = [roles.error];
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return {
    ok: true,
    value: { screen: screen as TeamScreenId, contact, displayName, roles: roles.roles },
  };
}

export interface RolesForm {
  screen: TeamScreenId;
  userId: string;
  roles: Role[];
}

export function parseRolesForm(formData: FormData, kind: TenantKind): ParsedForm<RolesForm> {
  const errors: Record<string, string[]> = {};
  const screen = stringField(formData, TEAM_FIELDS.screen);
  if (!isTeamScreenId(screen)) errors.screen = [t("team.form.screenUnknown")];
  const userId = stringField(formData, TEAM_FIELDS.userId).trim();
  if (userId === "") errors.userId = [t("team.form.memberUnknown")];
  const roles = rolesField(formData, kind);
  if (roles.error !== undefined) errors.roles = [roles.error];
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return { ok: true, value: { screen: screen as TeamScreenId, userId, roles: roles.roles } };
}

export interface DisableForm {
  screen: TeamScreenId;
  userId: string;
  reason: string;
}

export const DISABLE_REASON_MIN_LENGTH = 10;

export function parseDisableForm(formData: FormData): ParsedForm<DisableForm> {
  const errors: Record<string, string[]> = {};
  const screen = stringField(formData, TEAM_FIELDS.screen);
  if (!isTeamScreenId(screen)) errors.screen = [t("team.form.screenUnknown")];
  const userId = stringField(formData, TEAM_FIELDS.userId).trim();
  if (userId === "") errors.userId = [t("team.form.memberUnknown")];
  const reason = stringField(formData, TEAM_FIELDS.reason).trim();
  if (reason.length < DISABLE_REASON_MIN_LENGTH) {
    errors.reason = [t("team.form.reasonTooShort", { min: DISABLE_REASON_MIN_LENGTH })];
  }
  if (Object.keys(errors).length > 0) return { ok: false, fieldErrors: errors };
  return {
    ok: true,
    value: { screen: screen as TeamScreenId, userId, reason: reason.slice(0, 500) },
  };
}
