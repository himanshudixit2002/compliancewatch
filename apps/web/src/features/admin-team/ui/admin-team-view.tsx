import type { Route } from "next";
import Link from "next/link";
import { Button, EmptyState, PageHeader } from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { StatCard } from "@/shared/ui/stat-card";
import {
  ROLE_LABEL,
  ROLE_TONE,
  STATUS_LABEL,
  STATUS_TONE,
  adminTeamSummary,
  heldRoles,
} from "../model/admin-team";
import type { AdminMember } from "../model/admin-team";
import type { MemberRow } from "./member-filter";
import { MemberTable } from "./member-table";

export interface AdminTeamViewProps {
  title: string;
  members: readonly AdminMember[];
  /** Where to add an internal user; the button is left out when absent. */
  addHref?: Route;
}

function memberRow(member: AdminMember): MemberRow {
  return {
    id: member.id,
    name: member.name,
    email: member.email,
    roles: member.roles.map((role) => ({
      value: role,
      label: t(ROLE_LABEL[role]),
      tone: ROLE_TONE[role],
    })),
    status: {
      value: member.status,
      label: t(STATUS_LABEL[member.status]),
      tone: STATUS_TONE[member.status],
    },
    joined: formatDate(member.joinedAt),
  };
}

/**
 * The internal users page: a summary row (users, active, disabled, admins), then the users in
 * a table the admin can search by name or email and filter by role.
 */
export function AdminTeamView({ title, members, addHref }: AdminTeamViewProps) {
  const summary = adminTeamSummary(members);
  const actions =
    addHref === undefined ? undefined : (
      <Button asChild>
        <Link href={addHref}>{t("adminTeam.add")}</Link>
      </Button>
    );
  return (
    <div data-slot="admin-team" className="flex flex-col gap-6">
      <PageHeader title={title} description={t("adminTeam.intro")} actions={actions} />
      {members.length === 0 ? (
        <EmptyState title={t("adminTeam.emptyTitle")} body={t("adminTeam.emptyBody")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard label={t("adminTeam.stat.total")} value={summary.total} tone="info" />
            <StatCard label={t("adminTeam.stat.active")} value={summary.active} tone="success" />
            <StatCard
              label={t("adminTeam.stat.disabled")}
              value={summary.disabled}
              tone={summary.disabled > 0 ? "danger" : "neutral"}
            />
            <StatCard label={t("adminTeam.stat.admins")} value={summary.admins} tone="warning" />
          </div>
          <MemberTable
            rows={members.map(memberRow)}
            roles={heldRoles(members).map((role) => ({ value: role, label: t(ROLE_LABEL[role]) }))}
          />
        </>
      )}
    </div>
  );
}
