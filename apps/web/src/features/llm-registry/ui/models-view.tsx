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
import type { EditNote as EditNoteView, ModelRow } from "../model/registry";
import { EditNote } from "./edit-note";

export interface ModelsViewProps {
  title: string;
  crumbs: readonly Crumb[];
  rows: readonly ModelRow[];
  note: EditNoteView;
}

function List({ items }: { items: readonly string[] }) {
  if (items.length === 0) return <span className="text-fg-muted">{t("common.none")}</span>;
  return <code className="font-mono text-xs">{items.join(", ")}</code>;
}

/**
 * The gateway's model route for each feature, as the gateway reports it with any override
 * applied: the primary model and its fallback, the providers it may use or must offer, the sort,
 * the reasoning effort and the time limit, and whether the route is the default or set by the
 * gateway's environment (and which variable). Read-only.
 */
export function ModelsView({ title, crumbs, rows, note }: ModelsViewProps) {
  return (
    <div data-slot="llm-models" className="flex max-w-6xl flex-col gap-6">
      <PageHeader
        title={title}
        description={t("llm.models.intro")}
        breadcrumbs={<Breadcrumbs crumbs={crumbs} />}
      />
      <EditNote note={note} />
      {rows.length === 0 ? (
        <EmptyState title={t("llm.models.emptyTitle")} body={t("llm.models.emptyBody")} />
      ) : (
        <Table scrollLabel={t("llm.models.tableRegion")}>
          <TableCaption className="text-left text-sm text-fg-muted">
            {t("llm.models.caption", { count: rows.length })}
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>{t("llm.models.column.feature")}</TableHead>
              <TableHead>{t("llm.models.column.models")}</TableHead>
              <TableHead>{t("llm.models.column.providers")}</TableHead>
              <TableHead>{t("llm.models.column.settings")}</TableHead>
              <TableHead>{t("llm.models.column.source")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.feature} data-feature={row.feature}>
                <TableCell className="align-top text-sm font-medium">{row.featureLabel}</TableCell>
                <TableCell className="align-top text-sm">
                  <div className="flex flex-col gap-1">
                    <span>
                      {t("llm.models.primary")}{" "}
                      <code className="font-mono text-xs">{row.primary}</code>
                    </span>
                    <span>
                      {t("llm.models.fallback")}{" "}
                      {row.fallback === null ? (
                        <span className="text-fg-muted">{t("common.none")}</span>
                      ) : (
                        <code className="font-mono text-xs">{row.fallback}</code>
                      )}
                    </span>
                  </div>
                </TableCell>
                <TableCell className="align-top text-sm">
                  <div className="flex flex-col gap-1">
                    <span>
                      {t("llm.models.only")} <List items={row.only} />
                    </span>
                    <span>
                      {t("llm.models.has")} <List items={row.has} />
                    </span>
                  </div>
                </TableCell>
                <TableCell className="align-top text-sm">
                  <div className="flex flex-col gap-1">
                    <span>{t("llm.models.sort", { sort: row.sort ?? t("common.none") })}</span>
                    <span>
                      {t("llm.models.effort", { effort: row.reasoningEffort ?? t("common.none") })}
                    </span>
                    <span>{t("llm.models.timeout", { timeout: row.timeout })}</span>
                  </div>
                </TableCell>
                <TableCell className="align-top text-sm">
                  <div className="flex flex-col gap-1">
                    <StatusChip
                      status={row.overridden ? "override" : "default"}
                      tone={row.overridden ? "info" : "neutral"}
                      label={row.sourceLabel}
                    />
                    {row.variable === null ? null : (
                      <code className="font-mono text-xs text-fg-muted">{row.variable}</code>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
