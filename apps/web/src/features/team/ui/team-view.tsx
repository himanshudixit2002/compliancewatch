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
import { InviteDialog } from "./invite-dialog";
import type { TeamAction, TeamFormFields, TeamRoleOption } from "./invite-dialog";
import { MemberActions } from "./member-actions";

/** What the page adds for a tenant admin: the invite dialog and each member's controls. */
export interface TeamManagement {
  screenId: string;
  currentUserId: string;
  fields: TeamFormFields;
  roles: readonly TeamRoleOption[];
  /** The one active admin, when there is only one, who cannot be demoted or disabled. */
  lastAdminId: string | null;
  billingHref: string | null;
  actions: { invite: TeamAction; changeRoles: TeamAction; disable: TeamAction };
  /** The internal tenant's page says which roles sign in with a second factor. */
  mfaNote?: string;
}

export interface TeamViewProps {
  title: string;
  members: readonly TeamMember[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  management?: TeamManagement;
  intro?: string;
}

function MemberRow({ member, management }: { member: TeamMember; management?: TeamManagement }) {
  return (
    <TableRow data-member={member.id}>
      <TableCell className="font-medium text-fg">
        {member.name || t("team.unnamed")}
        {management !== undefined && member.id === management.currentUserId ? (
          <span className="ml-2 text-xs text-fg-muted">{t("team.you")}</span>
        ) : null}
      </TableCell>
      <TableCell>{member.email || member.phone || t("common.none")}</TableCell>
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
      {management !== undefined ? (
        <TableCell>
          {member.status === "active" ? (
            <MemberActions
              member={{ id: member.id, name: member.name || member.email, roles: member.roles }}
              screenId={management.screenId}
              fields={management.fields}
              roles={management.roles}
              changeRoles={management.actions.changeRoles}
              disable={management.actions.disable}
              isSelf={member.id === management.currentUserId}
              lastAdmin={member.id === management.lastAdminId}
            />
          ) : (
            <span className="text-sm text-fg-muted">{t("team.noActions")}</span>
          )}
        </TableCell>
      ) : null}
    </TableRow>
  );
}

/**
 * The team page: the settings header, a summary row (members, active, disabled) and a table
 * of each member's name, contact, roles, status and the date they joined, active first. With
 * `management` (a tenant admin on the page) the header offers the invite dialog and each
 * active row its roles and disable dialogs; a disabled row shows its status and no controls.
 */
export function TeamView({ title, members, crumbs, tabs, management, intro }: TeamViewProps) {
  const summary = teamSummary(members);
  const invite =
    management === undefined ? undefined : (
      <InviteDialog
        action={management.actions.invite}
        screenId={management.screenId}
        fields={management.fields}
        roles={management.roles}
        billingHref={management.billingHref}
      />
    );
  return (
    <div data-slot="team" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={intro ?? t("team.intro")}
        crumbs={crumbs}
        tabs={tabs}
        actions={invite}
      />
      {management?.mfaNote ? (
        <p className="text-sm text-fg-muted" data-slot="team-mfa-note">
          {management.mfaNote}
        </p>
      ) : null}
      {members.length === 0 ? (
        <EmptyState title={t("team.emptyTitle")} body={t("team.emptyBody")} action={invite} />
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
                {management !== undefined ? (
                  <TableHead>{t("team.column.actions")}</TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortMembers(members).map((member) => (
                <MemberRow key={member.id} member={member} management={management} />
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
