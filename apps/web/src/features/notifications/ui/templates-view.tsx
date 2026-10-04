import {
  EmptyState,
  PageHeader,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@compliancewatch/ui";
import type { Crumb } from "@/shared/config/nav";
import { t } from "@/shared/i18n";
import { Breadcrumbs } from "@/shared/ui/breadcrumbs";
import { StatCard } from "@/shared/ui/stat-card";
import { templateCounts, type TemplateRow } from "../model/templates";

export interface TemplatesViewProps {
  title: string;
  crumbs: readonly Crumb[];
  rows: readonly TemplateRow[];
}

/**
 * The message templates the notification service holds: per key, channel and language, the name
 * it carries at Meta, its approval status there, its placeholders and its text. The text holds
 * placeholders only; the facts a message carries are filled in when it is sent.
 */
export function TemplatesView({ title, crumbs, rows }: TemplatesViewProps) {
  const counts = templateCounts(rows);
  return (
    <div data-slot="templates" className="flex flex-col gap-6">
      <PageHeader
        title={title}
        description={t("templates.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      {rows.length === 0 ? (
        <EmptyState title={t("templates.emptyTitle")} body={t("templates.emptyBody")} />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            <StatCard label={t("templates.stat.templates")} value={counts.templates} tone="info" />
            <StatCard label={t("templates.stat.keys")} value={counts.keys} />
          </div>
          <Table scrollLabel={t("templates.tableRegion")}>
            <TableCaption className="text-left text-sm text-fg-muted">
              {t("templates.caption", { count: rows.length })}
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>{t("templates.column.template")}</TableHead>
                <TableHead>{t("templates.column.channel")}</TableHead>
                <TableHead>{t("templates.column.status")}</TableHead>
                <TableHead>{t("templates.column.placeholders")}</TableHead>
                <TableHead>{t("templates.column.text")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow
                  key={`${row.key} ${row.channel} ${row.language}`}
                  data-template={`${row.key}:${row.channel}:${row.language}`}
                >
                  <TableCell className="align-top">
                    <div className="flex flex-col gap-1">
                      <code className="font-mono text-xs font-medium text-fg">{row.key}</code>
                      {row.metaName === "" ? null : (
                        <span className="text-xs text-fg-muted">
                          {t("templates.metaName", { name: row.metaName })}
                        </span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <div className="flex flex-col gap-1">
                      <span>{row.channelLabel}</span>
                      <span className="text-xs text-fg-muted">{row.languageLabel}</span>
                    </div>
                  </TableCell>
                  <TableCell className="align-top">
                    <StatusChip status={row.status} tone={row.tone} label={row.statusLabel} />
                  </TableCell>
                  <TableCell className="align-top">
                    {row.placeholders.length === 0 ? (
                      <span className="text-fg-muted">{t("common.none")}</span>
                    ) : (
                      <code className="font-mono text-xs">{row.placeholders.join(", ")}</code>
                    )}
                  </TableCell>
                  <TableCell className="min-w-80 align-top text-sm whitespace-pre-wrap text-fg">
                    {row.body}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </div>
  );
}
