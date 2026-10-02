import type { Metadata } from "next";
import { requireScreenSession } from "@/server/dal";
import { AdminTeamView } from "@/features/admin-team";
import { screenById } from "@/shared/config/screens";

const SCREEN = screenById("admin.team");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

export default async function AdminTeamPage() {
  const session = await requireScreenSession(SCREEN);
  const members: any[] = [];
  const invitations: any[] = [];
  return (
    <AdminTeamView
      view={{
        members,
        pendingInvitations: invitations,
        totalMembers: members.length,
        availableRoles: ["admin", "staff", "compliance_lead", "viewer"],
      }}
    />
  );
}
