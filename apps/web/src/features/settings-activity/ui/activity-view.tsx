import type { Route } from "next";
import Link from "next/link";
import {
  Button,
  EmptyState,
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
import { formatDateTime } from "@/shared/lib/dates";
import { SettingsHeader } from "@/shared/ui/settings-header";
import { actionLabel, actorLabel, newestFirst } from "../model/activity";
import type { ActivityEntry } from "../model/activity";

export interface ActivityViewProps {
  title: string;
  entries: readonly ActivityEntry[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
  /** The next page of older entries, from the trail's cursor; the link is left out without it. */
  olderHref?: Route;
}

function EntryRow({ entry }: { entry: ActivityEntry }) {
  return (
    <TableRow data-activity={entry.id}>
      <TableCell className="text-fg-muted">{formatDateTime(entry.at)}</TableCell>
      <TableCell className={entry.actor === null ? "text-fg-muted" : "text-fg"}>
        {actorLabel(entry.actor)}
      </TableCell>
      <TableCell className="font-medium text-fg">{actionLabel(entry.action)}</TableCell>
      <TableCell className="whitespace-normal">{entry.subject}</TableCell>
    </TableRow>
  );
}

/**
 * The activity settings page: the settings header, then the audit trail newest first, each
 * entry with when it happened, who made the change (or the service, for an automatic one), what
 * was done and what it applied to, and a link to older entries when there are more.
 */
export function ActivityView({ title, entries, crumbs, tabs, olderHref }: ActivityViewProps) {
  return (
    <div data-slot="activity" className="flex flex-col gap-6">
      <SettingsHeader
        title={title}
        description={t("settingsActivity.intro")}
        crumbs={crumbs}
        tabs={tabs}
      />
      {entries.length === 0 ? (
        <EmptyState
          title={t("settingsActivity.emptyTitle")}
          body={t("settingsActivity.emptyBody")}
        />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("settingsActivity.caption")}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("settingsActivity.column.when")}</TableHead>
              <TableHead>{t("settingsActivity.column.who")}</TableHead>
              <TableHead>{t("settingsActivity.column.action")}</TableHead>
              <TableHead>{t("settingsActivity.column.subject")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {newestFirst(entries).map((entry) => (
              <EntryRow key={entry.id} entry={entry} />
            ))}
          </TableBody>
        </Table>
      )}
      {olderHref === undefined ? null : (
        <Button asChild variant="secondary" className="self-start">
          <Link href={olderHref}>{t("settingsActivity.older")}</Link>
        </Button>
      )}
    </div>
  );
}
