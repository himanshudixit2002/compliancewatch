import { Badge, StatusChip, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { EmptyState } from "@/shared/ui/components/empty-state-view";
import { SettingsHeader } from "@/shared/ui/settings-header";
import { StatCard } from "@/shared/ui/components/stat-card";
import type { TeamMemberView } from "../model/team";

export interface TeamViewProps {
  title: string;
  items: readonly TeamMemberView[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
}

const ROLE_TONE: Record<string, "info" | "warning" | "neutral" | "success" | "danger"> = {
  owner: "info",
  ca_admin: "warning",
  admin: "warning",
  staff: "neutral",
  ca_staff: "neutral",
  compliance_lead: "info",
  analyst: "neutral",
  reviewer: "neutral",
};

function RoleBadge({ role }: { role: string }) {
  return <Badge tone={ROLE_TONE[role] ?? "neutral"}>{t(`role.${role}`, role)}</Badge>;
}

function StatCards({ items }: { items: readonly TeamMemberView[] }) {
  const total = items.length;
  const active = items.filter((m) => m.status === "active").length;
  const invited = items.filter((m) => m.status === "invited").length;
  const disabled = items.filter((m) => m.status === "disabled").length;

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <StatCard label={t("team.stat.total")} value={total} tone="info" />
      <StatCard label={t("team.stat.active")} value={active} tone="success" />
      <StatCard label={t("team.stat.invited")} value={invited} tone="warning" />
      <StatCard label={t("team.stat.disabled")} value={disabled} tone="danger" />
    </div>
  );
}

function MemberStatus({ status }: { status: TeamMemberView["status"] }) {
  const tone = status === "active" ? "success" : status === "invited" ? "warning" : "danger";
  const label = status === "active" ? t("team.status.active") : status === "invited" ? t("team.status.invited") : t("team.status.disabled");
  return <StatusChip status={status} tone={tone} label={label} />;
}

/**
 * The team members page: the settings header (breadcrumbs, title and tabs), a summary row
 * of stat cards, and, when members exist, a table of their name, email, role, status and
 * activity. The role column uses badges so the colour makes the table scannable; the
 * status column uses a dot-and-label chip.
 */
export function TeamView({ title, items, crumbs, tabs }: TeamViewProps) {
  return (
    <div data-slot="team" className="flex max-w-4xl flex-col gap-6">
      <SettingsHeader title={title} description={t("team.intro")} crumbs={crumbs} tabs={tabs} />
      {items.length === 0 ? (
        <EmptyState title={t("team.emptyTitle")} description={t("team.emptyDescription")} />
      ) : (
        <>
          <StatCards items={items} />
          <div className="overflow-hidden rounded-md border border-line">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("team.column.name")}</TableHead>
                  <TableHead>{t("team.column.email")}</TableHead>
                  <TableHead>{t("team.column.role")}</TableHead>
                  <TableHead>{t("team.column.status")}</TableHead>
                  <TableHead>{t("team.column.joined")}</TableHead>
                  <TableHead>{t("team.column.lastActive")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((member) => (
                  <TableRow key={member.id}>
                    <TableCell className="font-medium text-fg">{member.name}</TableCell>
                    <TableCell>{member.email}</TableCell>
                    <TableCell>
                      <RoleBadge role={member.role} />
                    </TableCell>
                    <TableCell>
                      <MemberStatus status={member.status} />
                    </TableCell>
                    <TableCell>{member.joinedAt}</TableCell>
                    <TableCell className="text-fg-muted">{member.lastActiveAt ?? "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </>
      )}
    </div>
  );
}
