"use client";

import { Badge, EmptyState, Table, TableBody, TableCaption, TableCell, TableHead, TableHeader, TableRow } from "@compliancewatch/ui";
import type { BadgeTone } from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { formatDate } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import type { ActivityEntry, ActivityView } from "../model/activity";

export interface ActivityViewProps {
  title: string;
  view: ActivityView;
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
}

const ACTION_TONE: Readonly<Record<string, BadgeTone>> = {
  sign_in: "success",
  sign_out: "neutral",
  consent_grant: "info",
  consent_withdraw: "warning",
  profile_update: "info",
  business_added: "success",
  user_invited: "info",
  role_changed: "warning",
  user_disabled: "danger",
  subscription_started: "success",
  subscription_cancelled: "danger",
};

function ActionBadge({ action }: { action: string }) {
  const tone = ACTION_TONE[action] ?? "neutral";
  return <Badge tone={tone}>{action}</Badge>;
}

function EntryRow({ entry }: { entry: ActivityEntry }) {
  return (
    <TableRow data-activity-id={entry.id}>
      <TableCell className="text-fg-muted whitespace-nowrap">{formatDate(entry.timestamp)}</TableCell>
      <TableCell>
        <ActionBadge action={entry.action} />
      </TableCell>
      <TableCell className="max-w-xs truncate">{entry.description}</TableCell>
      <TableCell className="font-mono text-xs text-fg-muted">{entry.ipAddress}</TableCell>
    </TableRow>
  );
}

/**
 * The activity log settings page: the settings header and a table of account actions with their
 * timestamps, descriptions and the IP addresses they came from, newest first.
 */
export function ActivityView({ title, view, crumbs, tabs }: ActivityViewProps) {
  return (
    <div data-slot="activity" className="flex flex-col gap-6">
      <SettingsHeader title={title} description={t("settings.about.owner.settings.activity")} crumbs={crumbs} tabs={tabs} />
      {view.entries.length === 0 ? (
        <EmptyState title={t("dashboard.activityEmptyTitle")} body={t("dashboard.activityEmptyBody")} />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("dashboard.activityTitle")} — {view.totalCount} {view.totalCount === 1 ? "entry" : "entries"}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Timestamp</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Description</TableHead>
              <TableHead>IP address</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {view.entries.map((entry) => (
              <EntryRow key={entry.id} entry={entry} />
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
