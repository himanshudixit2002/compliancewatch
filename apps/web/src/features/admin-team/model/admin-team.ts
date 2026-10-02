import type { MemberRole, MemberStatus } from "@/entities/session/types";
import { t } from "@/shared/i18n";

export interface AdminTeamView {
  members: AdminMember[];
  pendingInvitations: AdminInvitation[];
  totalMembers: number;
  availableRoles: readonly string[];
}

export interface AdminMember {
  id: string;
  userId: string;
  name: string;
  email: string;
  role: string;
  roleLabel: string;
  status: string;
  joinedAt: string;
  lastActiveAt: string;
}

export interface AdminInvitation {
  id: string;
  email: string;
  role: string;
  roleLabel: string;
  invitedBy: string;
  invitedAt: string;
  expiresAt: string;
}

export function emptyAdminTeam(): AdminTeamView {
  return {
    members: [],
    pendingInvitations: [],
    totalMembers: 0,
    availableRoles: ["admin", "staff", "compliance_lead", "viewer"],
  };
}

export function memberStatusBadge(status: string) {
  return t(`admin.team.status.${status}`);
}

export function memberRoleBadge(role: string) {
  return t(`admin.team.role.${role}`);
}
