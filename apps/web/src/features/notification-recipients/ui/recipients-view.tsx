import {
  Badge,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb, NavLink } from "@/shared/config/nav";
import { SettingsHeader } from "@/shared/ui/settings-header";
import { EmptyState } from "@/shared/ui/components/empty-state-view";
import { t } from "@/shared/i18n";
import type { RecipientView } from "../model/recipients";

export interface RecipientsViewProps {
  title: string;
  items: readonly RecipientView[];
  crumbs: readonly Crumb[];
  tabs: readonly NavLink[];
}

/** Recipients table: who receives reminders, on which channel, opted in or out. */
export function RecipientsView({ title, items, crumbs, tabs }: RecipientsViewProps) {
  return (
    <div data-slot="recipients" className="flex flex-col gap-6">
      <SettingsHeader title={title} description={t("recipients.intro")} crumbs={crumbs} tabs={tabs} />
      {items.length === 0 ? (
        <EmptyState title={t("recipients.emptyTitle")} description={t("recipients.emptyBody")} />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("recipients.caption", { count: items.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("recipients.column.channel")}</TableHead>
              <TableHead>{t("recipients.column.address")}</TableHead>
              <TableHead>{t("recipients.column.optedIn")}</TableHead>
              <TableHead>{t("recipients.column.language")}</TableHead>
              <TableHead>{t("recipients.column.quietHours")}</TableHead>
              <TableHead>{t("recipients.column.updatedAt")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.id}>
                <TableCell>
                  <Badge tone="neutral">{t(`notifications.channel.${item.channel}`)}</Badge>
                </TableCell>
                <TableCell className="font-mono text-xs">{item.address}</TableCell>
                <TableCell>
                  <StatusChip
                    status={item.optedIn ? "opted_in" : "opted_out"}
                    tone={item.optedIn ? "success" : "danger"}
                    label={item.optedIn ? t("recipients.status.optedIn") : t("recipients.status.optedOut")}
                  />
                </TableCell>
                <TableCell>{item.language.toUpperCase()}</TableCell>
                <TableCell className="text-fg-muted">
                  {item.quietHoursStart} – {item.quietHoursEnd}
                </TableCell>
                <TableCell className="text-fg-muted">{item.updatedAt}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
