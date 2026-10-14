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
import { breadcrumbsFor } from "@/shared/config/nav";
import { hrefFor, screenById } from "@/shared/config/screens";
import { t } from "@/shared/i18n";
import { ServiceError } from "@/shared/ui/service-error";

const SCREEN = screenById("admin.team");

export const metadata: Metadata = { title: SCREEN.title };

export const dynamic = "force-dynamic";

/** The regulatory team's users, for its admin: the same four identity routes as a tenant's team. */
export default async function AdminTeamPage() {
  const session = await requireScreenSession(SCREEN);
  await requireMfa({ next: hrefFor(SCREEN) });
  const team = await getTeam(session);
  if (!team.ok) return <ServiceError heading={SCREEN.title} error={team.error} />;
  const members = team.value;
  const admins = members.filter((member) => isLastAdmin(members, member.id, session.tenantKind));
  return (
    <TeamView
      title={SCREEN.title}
      intro={t("team.internalIntro")}
      members={members}
      crumbs={breadcrumbsFor("admin.team")}
      tabs={[]}
      management={{
        screenId: SCREEN.id,
        currentUserId: session.userId,
        fields: TEAM_FIELDS,
        roles: roleOptionsFor(session.tenantKind),
        lastAdminId: admins[0]?.id ?? null,
        billingHref: null,
        actions: { invite: inviteMember, changeRoles: changeMemberRoles, disable: disableMember },
        mfaNote: t("team.internalMfaNote"),
      }}
    />
  );
}
