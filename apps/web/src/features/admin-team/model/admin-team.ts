import type { Tone } from "@compliancewatch/ui";
import type { identity } from "@compliancewatch/contracts/openapi";
import { ROLES } from "@/shared/config/roles";
import type { Role } from "@/shared/config/roles";
import type { MessageKey } from "@/shared/i18n";

/**
 * The internal users screen's model: the internal tenant's users as `GET /v1/identity/users`
 * returns them, the role and status wording, and the counts for the summary row.
 */
export type UserDto = identity.components["schemas"]["UserOut"];
export type AdminMemberStatus = identity.components["schemas"]["UserStatus"];

export interface AdminMember {
  id: string;
  name: string;
  email: string;
  roles: readonly Role[];
  status: AdminMemberStatus;
  /** When the user was added, an ISO instant. */
  joinedAt: string;
}

export interface AdminTeamSummary {
  total: number;
  active: number;
  disabled: number;
  /** Members holding the admin role, who manage the others. */
  admins: number;
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

/** Admin stands out; a reviewer approves what analysts propose; the rest read as neutral. */
export const ROLE_TONE: Readonly<Record<Role, Tone>> = {
  admin: "warning",
  reviewer: "info",
  analyst: "neutral",
  owner: "neutral",
  staff: "neutral",
  ca_admin: "neutral",
  ca_staff: "neutral",
  compliance_lead: "neutral",
};

export const STATUS_LABEL: Readonly<Record<AdminMemberStatus, MessageKey>> = {
  active: "adminTeam.status.active",
  disabled: "adminTeam.status.disabled",
};

export const STATUS_TONE: Readonly<Record<AdminMemberStatus, Tone>> = {
  active: "success",
  disabled: "danger",
};

export function adminMemberFromDto(dto: UserDto): AdminMember {
  return {
    id: dto.id,
    name: dto.display_name,
    email: dto.email,
    roles: dto.roles,
    status: dto.status,
    joinedAt: dto.created_at,
  };
}

export function adminTeamSummary(members: readonly AdminMember[]): AdminTeamSummary {
  const active = members.filter((member) => member.status === "active").length;
  return {
    total: members.length,
    active,
    disabled: members.length - active,
    admins: members.filter((member) => member.roles.includes("admin")).length,
  };
}

/** The roles the members hold, in the order roles.ts lists them, for the role filter. */
export function heldRoles(members: readonly AdminMember[]): Role[] {
  const held = new Set(members.flatMap((member) => member.roles));
  return ROLES.filter((role) => held.has(role));
}
