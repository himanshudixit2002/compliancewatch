import type { Tone } from "@compliancewatch/ui";
import type { identity } from "@compliancewatch/contracts/openapi";
import type { Role } from "@/shared/config/roles";
import type { MessageKey } from "@/shared/i18n";

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
