import type { Metadata } from "next";
import {
  TEAM_FIELDS,
  TeamView,
  changeMemberRoles,
  disableMember,
  getTeam,
  inviteMember,
  isLastAdmin,
  roleOptionsFor,
} from "@/features/team";
import { requireMfa, requireScreenSession } from "@/server/dal";
import { settingsHeaderLinks } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("owner.settings.team");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

/** The tenant's people, for its owner or CA admin: list, invite, change roles, disable. */
export default async function TeamPage() {
  const session = await requireScreenSession(SCREEN);
  await requireMfa({ next: hrefFor(SCREEN) });
  const team = await getTeam(session);
  const { crumbs, tabs } = settingsHeaderLinks(SCREEN, session);
  if (!team.ok) return <ServiceError heading={SCREEN.title} error={team.error} />;
  const members = team.value;
  const admins = members.filter((member) => isLastAdmin(members, member.id, session.tenantKind));
  return (
    <TeamView
      title={SCREEN.title}
      members={members}
      crumbs={crumbs}
      tabs={tabs}
      management={{
        screenId: SCREEN.id,
        currentUserId: session.userId,
        fields: TEAM_FIELDS,
        roles: roleOptionsFor(session.tenantKind),
        lastAdminId: admins[0]?.id ?? null,
        billingHref: hrefFor(screenById("owner.settings.billing")),
        actions: { invite: inviteMember, changeRoles: changeMemberRoles, disable: disableMember },
      }}
    />
  );
}
