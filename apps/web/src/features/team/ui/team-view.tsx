import {
  Badge,
  EmptyState,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import { StatCard } from "@/shared/ui/stat-card";
import {
  ROLE_LABEL,
  ROLE_TONE,
  STATUS_LABEL,
  STATUS_TONE,
  sortMembers,
  teamSummary,
} from "../model/team";
import type { TeamMember } from "../model/team";

export interface TeamViewProps {
  title: string;
  members: readonly TeamMember[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
}

function MemberRow({ member }: { member: TeamMember }) {
  return (
    <TableRow data-member={member.id}>
      <TableCell className="font-medium text-fg">{member.name}</TableCell>
      <TableCell>{member.email}</TableCell>
      <TableCell>
        {member.roles.length === 0 ? (
          <span className="text-fg-muted">{t("common.none")}</span>
        ) : (
          <ul className="flex flex-wrap gap-1">
            {member.roles.map((role) => (
              <li key={role}>
                <Badge tone={ROLE_TONE[role]}>{t(ROLE_LABEL[role])}</Badge>
              </li>
            ))}
          </ul>
        )}
      </TableCell>
      <TableCell>
        <StatusChip
          status={member.status}
          tone={STATUS_TONE[member.status]}
          label={t(STATUS_LABEL[member.status])}
        />
      </TableCell>
      <TableCell className="text-fg-muted">{formatDate(member.joinedAt)}</TableCell>
    </TableRow>
  );
}

/**
 * The team settings page: the settings header, a summary row (members, active, disabled) and a
 * table of each member's name, email, roles, status and the date they joined, active first.
 */
export function TeamView({ title, members, crumbs, tabs }: TeamViewProps) {
  const summary = teamSummary(members);
  return (
    <div data-slot="team" className="flex flex-col gap-6">
      <SettingsHeader title={title} description={t("team.intro")} crumbs={crumbs} tabs={tabs} />
      {members.length === 0 ? (
        <EmptyState title={t("team.emptyTitle")} body={t("team.emptyBody")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-3">
            <StatCard label={t("team.stat.total")} value={summary.total} tone="info" />
            <StatCard label={t("team.stat.active")} value={summary.active} tone="success" />
            <StatCard
              label={t("team.stat.disabled")}
              value={summary.disabled}
              tone={summary.disabled > 0 ? "danger" : "neutral"}
            />
          </div>
          <Table>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("team.caption", { count: members.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("team.column.name")}</TableHead>
                <TableHead>{t("team.column.email")}</TableHead>
                <TableHead>{t("team.column.roles")}</TableHead>
                <TableHead>{t("team.column.status")}</TableHead>
                <TableHead>{t("team.column.joined")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortMembers(members).map((member) => (
                <MemberRow key={member.id} member={member} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
