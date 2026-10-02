import {
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import { EmptyState } from "@/shared/ui/components/empty-state-view";
import { t } from "@/shared/i18n";
import type { FlagView } from "../model/flags";

export interface FlagsViewProps {
  title: string;
  items: readonly FlagView[];
}

/** Admin flags table: name, description, enabled status and change info. */
export function FlagsView({ title, items }: FlagsViewProps) {
  return (
    <div data-slot="flags" className="flex flex-col gap-6">
      <PageHeader title={title} description={t("flags.intro")} />
      {items.length === 0 ? (
        <EmptyState title={t("flags.emptyTitle")} description={t("flags.emptyBody")} />
      ) : (
        <Table>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("flags.caption", { count: items.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("flags.column.name")}</TableHead>
              <TableHead>{t("flags.column.description")}</TableHead>
              <TableHead>{t("flags.column.enabled")}</TableHead>
              <TableHead>{t("flags.column.changedAt")}</TableHead>
              <TableHead>{t("flags.column.changedBy")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.name}>
                <TableCell className="font-mono text-xs font-medium text-fg">{item.name}</TableCell>
                <TableCell className="text-fg">{item.description}</TableCell>
                <TableCell>
                  <StatusChip
                    status={item.enabled ? "enabled" : "disabled"}
                    tone={item.enabled ? "success" : "danger"}
                    label={item.enabled ? t("flags.status.enabled") : t("flags.status.disabled")}
                  />
                </TableCell>
                <TableCell className="text-fg-muted">{item.changedAt}</TableCell>
                <TableCell className="text-fg-muted">{item.changedBy}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
