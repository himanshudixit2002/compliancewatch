import type { Route } from "next";
import Link from "next/link";
import {
  Badge,
  StatusChip,
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  cn,
} from "@compliancewatch/ui";
import { t } from "@/shared/i18n";
import { ApplicabilityBadge } from "@/shared/ui/applicability";
import type { ObligationRow } from "../model/list";

export interface ObligationsTableProps {
  rows: readonly ObligationRow[];
  /** Whether a row names the node it is kept for (a business with several registrations). */
  showNode: boolean;
}

/**
 * A page of obligations by due date: the title (which opens the obligation) with its period and
 * the GSTIN it is kept for, the status, the due date in India with how it relates to today (an
 * overdue one says so in words), whether its rule has been reviewed with its citations, and the
 * engine's latest decision of the rule for the node it is kept for.
 */
export function ObligationsTable({ rows, showNode }: ObligationsTableProps) {
  return (
    <Table data-slot="obligations-table" scrollLabel={t("obligations.tableRegion")}>
      <TableCaption className="text-left text-sm text-fg-muted">
        {t("obligations.caption", { count: rows.length })}
      </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{t("obligations.column.obligation")}</TableHead>
          <TableHead scope="col">{t("obligations.column.status")}</TableHead>
          <TableHead scope="col">{t("obligations.column.due")}</TableHead>
          <TableHead scope="col">{t("obligations.column.rule")}</TableHead>
          <TableHead scope="col">{t("obligations.column.decision")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id} data-obligation={row.id} data-status={row.status}>
            <TableCell className="align-top whitespace-normal">
              <div className="flex flex-col gap-1">
                <Link
                  href={row.href as Route}
                  className="font-medium text-primary underline-offset-2 hover:underline"
                >
                  {row.title}
                </Link>
                {row.period === null ? null : (
                  <span className="text-xs text-fg-muted">{row.period}</span>
                )}
                {showNode && row.node !== null ? (
                  <span className="text-xs text-fg-muted">{row.node}</span>
                ) : null}
              </div>
            </TableCell>
            <TableCell className="align-top">
              <StatusChip status={row.status} tone={row.statusTone} label={row.statusLabel} />
            </TableCell>
            <TableCell className="align-top whitespace-nowrap">
              <span className="block">{row.due}</span>
              {row.dueNote === null ? null : (
                <span
                  data-slot="due-note"
                  className={cn(
                    "block text-xs",
                    row.overdue ? "font-medium text-danger" : "text-fg-muted",
                  )}
                >
                  {row.dueNote}
                </span>
              )}
            </TableCell>
            <TableCell className="align-top">
              <div className="flex flex-col items-start gap-1">
                <Badge tone={row.review.tone}>{row.review.label}</Badge>
                <span className="text-xs text-fg-muted">
                  {row.citations === 1
                    ? t("obligations.citationsOne")
                    : t("obligations.citationsMany", { count: row.citations })}
                </span>
              </div>
            </TableCell>
            <TableCell className="align-top" data-slot="row-decision">
              {row.applicability === null ? null : row.applicability.state === "decided" ? (
                <ApplicabilityBadge
                  result={row.applicability.result}
                  needsReview={row.applicability.needsReview}
                />
              ) : (
                <span className="text-xs text-fg-muted">
                  {row.applicability.state === "none"
                    ? t("obligations.decision.none")
                    : t("obligations.decision.unknown")}
                </span>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
